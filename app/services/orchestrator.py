import ast
import json
from collections import defaultdict

from app.services.initiative_prioritization import prioritize_initiatives

from app.models.schemas import (
    StrategyInput,
    StrategyOutcomesKPIsInput,
    StrategyInitiativesInput,
    StrategyReviewInput,
    FramingOutput,
    OutcomesKPIsOutput,
    InitiativesOutput,
    KPIIntegrityOutput,
    PortfolioOutput,
    NarrativeOutput,
)
from app.services.parser import (
    build_framing_context,
    build_strategy_context_from_mapping_input,
)
from app.services.llm import call_llm_json
from app.services.scoring import calculate_strategy_score

from app.agents.strategy_framing_agent import SYSTEM_PROMPT as FRAMING_PROMPT
from app.agents.strategy_outcomes_kpis_agent import SYSTEM_PROMPT as OUTCOMES_KPIS_PROMPT
from app.agents.strategy_initiatives_agent import SYSTEM_PROMPT as INITIATIVES_PROMPT
from app.agents.kpi_integrity_agent import SYSTEM_PROMPT as KPI_PROMPT
from app.agents.portfolio_intelligence_agent import SYSTEM_PROMPT as PORTFOLIO_PROMPT
from app.agents.narrative_agent import SYSTEM_PROMPT as NARRATIVE_PROMPT


def _dict_values_as_list(value):
    if isinstance(value, dict):
        return list(value.values())
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _normalize_string_list(values):
    normalized = []

    for item in values:
        if item is None:
            continue

        if isinstance(item, dict):
            description = str(item.get("description", "")).strip()
            implication = str(item.get("implication", "")).strip()

            if description and implication:
                normalized.append(f"{description} Implicação: {implication}")
            elif description:
                normalized.append(description)
            elif implication:
                normalized.append(implication)
            continue

        if isinstance(item, str):
            stripped = item.strip()

            if stripped.startswith("{") and stripped.endswith("}"):
                try:
                    parsed = ast.literal_eval(stripped)
                    if isinstance(parsed, dict):
                        description = str(parsed.get("description", "")).strip()
                        implication = str(parsed.get("implication", "")).strip()

                        if description and implication:
                            normalized.append(f"{description} Implicação: {implication}")
                        elif description:
                            normalized.append(description)
                        elif implication:
                            normalized.append(implication)
                        continue
                except Exception:
                    pass

            normalized.append(stripped)
            continue

        normalized.append(str(item))

    return [x for x in normalized if x]


# =========================================================
# FRAMING
# =========================================================
def normalize_framing(framing_data: dict) -> dict:
    framing_data = dict(framing_data or {})

    framing_data["strategic_themes"] = _dict_values_as_list(
        framing_data.get("strategic_themes", [])
    )
    framing_data["assumptions"] = _dict_values_as_list(
        framing_data.get("assumptions", [])
    )
    framing_data["contradictions"] = _dict_values_as_list(
        framing_data.get("contradictions", [])
    )

    normalized_themes = []
    for theme in framing_data["strategic_themes"]:
        if not isinstance(theme, dict):
            continue

        tradeoffs = _dict_values_as_list(theme.get("tradeoffs", []))
        not_doing = _dict_values_as_list(theme.get("not_doing", []))
        constraints = _dict_values_as_list(theme.get("constraints", []))

        normalized_themes.append(
            {
                "name": str(theme.get("name", "")).strip(),
                "description": str(theme.get("description", "")).strip(),
                "where_to_play": str(theme.get("where_to_play", "")).strip(),
                "how_to_win": str(theme.get("how_to_win", "")).strip(),
                "economic_logic": str(theme.get("economic_logic", "")).strip(),
                "tradeoffs": [str(x).strip() for x in tradeoffs if x is not None and str(x).strip()],
                "not_doing": [str(x).strip() for x in not_doing if x is not None and str(x).strip()],
                "constraints": [str(x).strip() for x in constraints if x is not None and str(x).strip()],
            }
        )

    framing_data["strategic_themes"] = normalized_themes
    framing_data["assumptions"] = _normalize_string_list(framing_data["assumptions"])
    framing_data["contradictions"] = _normalize_string_list(framing_data["contradictions"])

    return framing_data


def framing_is_incomplete(framing_data: dict) -> bool:
    themes = framing_data.get("strategic_themes", [])
    assumptions = framing_data.get("assumptions", [])
    contradictions = framing_data.get("contradictions", [])

    if not themes:
        return True
    if len(assumptions) < 3:
        return True
    if len(contradictions) < 2:
        return True

    for theme in themes:
        if not str(theme.get("where_to_play", "")).strip():
            return True
        if not str(theme.get("how_to_win", "")).strip():
            return True

    return False


def enrich_framing_if_incomplete(framing_data: dict, base_context: str) -> dict:
    if not framing_is_incomplete(framing_data):
        return framing_data

    repair_system_prompt = """
Você é um estrategista sênior e deve completar um framing estratégico incompleto.

Regras:
- strategic_themes deve ser lista
- assumptions deve ter no mínimo 3 itens
- contradictions deve ter no mínimo 2 itens
- cada tema deve conter:
  - name
  - description
  - where_to_play
  - how_to_win
  - economic_logic
  - tradeoffs
  - not_doing
  - constraints

Preserve o que estiver bom.
Complete só o que estiver faltando.
Retorne apenas JSON válido.
"""

    repair_user_prompt = f"""
CONTEXTO ORIGINAL:
{base_context}

FRAMING PRELIMINAR:
{json.dumps(framing_data, ensure_ascii=False)}

Complete o framing mantendo a lógica já construída.
"""

    repaired = call_llm_json(repair_system_prompt, repair_user_prompt)
    repaired = normalize_framing(repaired)

    for theme in repaired.get("strategic_themes", []):
        if not str(theme.get("where_to_play", "")).strip():
            theme["where_to_play"] = "Canais e segmentos prioritários definidos a partir dos principais motores de crescimento e rentabilidade da empresa."
        if not str(theme.get("how_to_win", "")).strip():
            theme["how_to_win"] = "Combinar diferenciação na proposta de valor com excelência operacional e disciplina econômica."

    if len(repaired.get("assumptions", [])) < 3:
        repaired["assumptions"] = repaired.get("assumptions", []) + [
            "A empresa conseguirá equilibrar crescimento e rentabilidade.",
            "Os investimentos em tecnologia gerarão ganhos reais de produtividade.",
            "A base de clientes responderá positivamente à proposta de valor."
        ]

    if len(repaired.get("contradictions", [])) < 2:
        repaired["contradictions"] = repaired.get("contradictions", []) + [
            "A empresa busca crescer, mas enfrenta limites de rentabilidade e capital.",
            "A diferenciação comercial pode aumentar complexidade operacional."
        ]

    repaired["assumptions"] = repaired["assumptions"][:6]
    repaired["contradictions"] = repaired["contradictions"][:4]

    return repaired


# =========================================================
# OUTCOMES + KPIS
# =========================================================
def normalize_outcomes_kpis(data: dict) -> dict:
    data = dict(data or {})
    data["outcomes"] = _dict_values_as_list(data.get("outcomes", []))
    data["kpis"] = _dict_values_as_list(data.get("kpis", []))

    normalized_outcomes = []
    outcome_names = set()

    for outcome in data["outcomes"]:
        if not isinstance(outcome, dict):
            continue

        name = str(outcome.get("name", "")).strip()
        if not name:
            continue

        normalized_outcomes.append(
            {
                "name": name,
                "linked_theme": str(outcome.get("linked_theme", "")).strip(),
                "target": str(outcome.get("target", "")).strip(),
                "timeframe": str(outcome.get("timeframe", "")).strip(),
                "value_driver": str(outcome.get("value_driver", "")).strip(),
            }
        )
        outcome_names.add(name)

    normalized_kpis = []
    for kpi in data["kpis"]:
        if not isinstance(kpi, dict):
            continue

        linked_outcomes = _dict_values_as_list(kpi.get("linked_outcomes", []))
        linked_outcomes = [
            str(x).strip() for x in linked_outcomes
            if str(x).strip() in outcome_names
        ]

        normalized_kpis.append(
            {
                "name": str(kpi.get("name", "")).strip(),
                "type": str(kpi.get("type", "")).strip().lower(),
                "level": str(kpi.get("level", "")).strip().lower(),
                "linked_outcomes": linked_outcomes,
                "target": str(kpi.get("target", "")).strip(),
                "owner": str(kpi.get("owner", "")).strip(),
                "formula": str(kpi.get("formula", "")).strip(),
                "source": str(kpi.get("source", "")).strip(),
            }
        )

    data["outcomes"] = normalized_outcomes
    data["kpis"] = normalized_kpis
    return data


# =========================================================
# INITIATIVES
# =========================================================
def normalize_initiatives(initiatives_data: dict, outcomes: list, kpis: list) -> dict:
    initiatives_data = dict(initiatives_data or {})
    initiatives_data["initiatives"] = _dict_values_as_list(
        initiatives_data.get("initiatives", [])
    )

    outcome_names = {o["name"] for o in outcomes}
    kpi_names = {k["name"] for k in kpis}

    normalized = []
    for item in initiatives_data["initiatives"]:
        if not isinstance(item, dict):
            continue

        linked_kpis = _dict_values_as_list(item.get("linked_kpis", []))
        linked_kpis = [str(x).strip() for x in linked_kpis if str(x).strip() in kpi_names]

        linked_outcome = str(item.get("linked_outcome", "")).strip()
        if linked_outcome not in outcome_names:
            linked_outcome = ""

        normalized.append(
            {
                "name": str(item.get("name", "")).strip(),
                "linked_theme": str(item.get("linked_theme", "")).strip(),
                "linked_outcome": linked_outcome,
                "linked_kpis": linked_kpis,
                "expected_impact": str(item.get("expected_impact", "")).strip(),
                "expected_kpi_delta": str(item.get("expected_kpi_delta", "")).strip(),
                "time_horizon": str(item.get("time_horizon", "")).strip(),
                "owner": str(item.get("owner", "")).strip(),
                "status": str(item.get("status", "")).strip().lower() or "planejado",
            }
        )

    initiatives_data["initiatives"] = normalized
    return initiatives_data


def enforce_kpi_outcome_links(outcomes: list, kpis: list) -> list:
    outcome_names = {o["name"] for o in outcomes}
    outcomes_by_theme = defaultdict(list)
    for outcome in outcomes:
        outcomes_by_theme[outcome["linked_theme"]].append(outcome["name"])

    fixed = []
    for kpi in kpis:
        linked_outcomes = [x for x in kpi.get("linked_outcomes", []) if x in outcome_names]

        if not linked_outcomes:
            text = f"{kpi.get('name', '')} {kpi.get('target', '')}".lower()

            for outcome in outcomes:
                oname = outcome["name"].lower()
                if any(token in text for token in oname.split() if len(token) > 4):
                    linked_outcomes = [outcome["name"]]
                    break

        fixed_kpi = dict(kpi)
        fixed_kpi["linked_outcomes"] = linked_outcomes
        fixed.append(fixed_kpi)

    return fixed


def enforce_initiative_links(outcomes: list, kpis: list, initiatives: list) -> list:
    outcome_names = {o["name"] for o in outcomes}
    kpis_by_outcome = defaultdict(list)

    for kpi in kpis:
        for linked_outcome in kpi.get("linked_outcomes", []):
            kpis_by_outcome[linked_outcome].append(kpi["name"])

    fixed = []
    for initiative in initiatives:
        linked_outcome = initiative.get("linked_outcome", "")
        linked_kpis = [k for k in initiative.get("linked_kpis", []) if k in {x["name"] for x in kpis}]

        if linked_outcome not in outcome_names:
            text = f"{initiative.get('name', '')} {initiative.get('expected_impact', '')}".lower()
            for outcome in outcomes:
                if any(token in text for token in outcome["name"].lower().split() if len(token) > 4):
                    linked_outcome = outcome["name"]
                    break

        if linked_outcome and not linked_kpis:
            linked_kpis = kpis_by_outcome.get(linked_outcome, [])[:2]

        fixed_item = dict(initiative)
        fixed_item["linked_outcome"] = linked_outcome
        fixed_item["linked_kpis"] = linked_kpis
        fixed.append(fixed_item)

    return fixed


def rebuild_strategy_graph(outcomes: list, kpis: list, initiatives: list) -> dict:
    lagging_by_outcome = defaultdict(list)
    leading_by_outcome = defaultdict(list)

    for kpi in kpis:
        for linked_outcome in kpi.get("linked_outcomes", []):
            if kpi.get("type") == "leading":
                leading_by_outcome[linked_outcome].append(kpi["name"])
            else:
                lagging_by_outcome[linked_outcome].append(kpi["name"])

    graph = {}
    for initiative in initiatives:
        linked_outcome = initiative.get("linked_outcome", "")
        linked_kpis = initiative.get("linked_kpis", [])

        kpi_leading = ""
        kpi_lagging = ""

        for k in linked_kpis:
            kobj = next((item for item in kpis if item["name"] == k), None)
            if not kobj:
                continue
            if kobj["type"] == "leading" and not kpi_leading:
                kpi_leading = k
            if kobj["type"] == "lagging" and not kpi_lagging:
                kpi_lagging = k

        if not kpi_leading and linked_outcome:
            candidates = leading_by_outcome.get(linked_outcome, [])
            kpi_leading = candidates[0] if candidates else ""

        if not kpi_lagging and linked_outcome:
            candidates = lagging_by_outcome.get(linked_outcome, [])
            kpi_lagging = candidates[0] if candidates else ""

        graph[initiative["name"]] = {
            "kpi_leading": kpi_leading,
            "kpi_lagging": kpi_lagging,
            "outcome": linked_outcome,
            "causal_logic": f"A iniciativa '{initiative['name']}' move KPI(s) {', '.join(linked_kpis)} e contribui para o outcome '{linked_outcome}'."
        }

    return graph


# =========================================================
# EXECUTIVE SUMMARY
# =========================================================
def build_executive_summary(
    payload: StrategyInput,
    framing: dict,
    outcomes: list,
    kpis: list,
    initiatives: list,
    review: dict,
) -> dict:
    strategy_score = review.get("strategy_score", {})
    narrative = review.get("narrative", {})

    company_name = payload.company_name or "Empresa"

    top_insights = [narrative.get("executive_summary", "")]
    for item in narrative.get("key_risks", [])[:2]:
        top_insights.append(item)

    priority_actions = []
    for rec in narrative.get("recommendations", [])[:4]:
        action = rec.get("action", "")
        if action:
            priority_actions.append(action)

    key_metrics = []
    for kpi in kpis[:5]:
        key_metrics.append(f"{kpi.get('name')}: {kpi.get('target')}")

    headline = (
        f"{company_name}: a direção estratégica está definida, "
        f"mas o valor vem da qualidade da cascata entre outcomes, KPIs e iniciativas."
    )

    final_takeaway = (
        f"Score estratégico atual: {strategy_score.get('overall_score', 'n/a')}. "
        "A robustez da execução depende de vínculos causais claros entre resultados, métricas e ações."
    )

    return {
        "headline": headline,
        "top_insights": top_insights,
        "priority_actions": priority_actions,
        "key_metrics": key_metrics,
        "final_takeaway": final_takeaway,
    }


# =========================================================
# INDIVIDUAL GENERATORS
# =========================================================
def generate_strategy_framing(payload: StrategyInput):
    base_context = build_framing_context(payload)

    framing_user_prompt = f"""
Construa o framing estratégico considerando os materiais abaixo.

IMPORTANTE:
- A estratégia deve respeitar explicitamente os guardrails de performance.
- Use os guardrails para definir trade-offs e constraints reais.

Materiais:
{base_context}
"""
    framing_data = call_llm_json(FRAMING_PROMPT, framing_user_prompt)
    framing_data = normalize_framing(framing_data)
    framing_data = enrich_framing_if_incomplete(framing_data, base_context)
    framing = FramingOutput(**framing_data)

    return {
        "framing": framing.model_dump()
    }


def generate_strategy_outcomes_kpis(payload: StrategyOutcomesKPIsInput):
    base_context = build_strategy_context_from_mapping_input(payload)
    framing = payload.framing

    user_prompt = f"""
Gere outcomes e KPIs com ligação causal explícita a partir do framing estratégico.

Framing:
{json.dumps(framing, ensure_ascii=False)}

Materiais originais:
{base_context}
"""
    data = call_llm_json(OUTCOMES_KPIS_PROMPT, user_prompt)
    data = normalize_outcomes_kpis(data)
    data["kpis"] = enforce_kpi_outcome_links(data["outcomes"], data["kpis"])

    outcomes_kpis = OutcomesKPIsOutput(**data)
    return outcomes_kpis.model_dump()


def generate_strategy_initiatives(payload: StrategyInitiativesInput):
    base_context = build_strategy_context_from_mapping_input(payload)
    framing = payload.framing
    outcomes = [o.model_dump() if hasattr(o, "model_dump") else o for o in payload.outcomes]
    kpis = [k.model_dump() if hasattr(k, "model_dump") else k for k in payload.kpis]

    user_prompt = f"""
Gere iniciativas executáveis com ligação explícita a outcomes e KPIs.

Framing:
{json.dumps(framing, ensure_ascii=False)}

Outcomes:
{json.dumps(outcomes, ensure_ascii=False)}

KPIs:
{json.dumps(kpis, ensure_ascii=False)}

Materiais originais:
{base_context}
"""
    data = call_llm_json(INITIATIVES_PROMPT, user_prompt)
    data = normalize_initiatives(data, outcomes, kpis)
    data["initiatives"] = enforce_initiative_links(outcomes, kpis, data["initiatives"])
    data = prioritize_initiatives(data)
    strategy_graph = rebuild_strategy_graph(outcomes, kpis, data.get("initiatives", []))

    result = {
        "initiatives": data.get("initiatives", []),
        "strategy_graph": strategy_graph,
    }

    initiatives = InitiativesOutput(**result)
    return initiatives.model_dump()


def generate_strategy_review(payload: StrategyReviewInput):
    framing = payload.framing
    outcomes = payload.outcomes
    kpis = payload.kpis
    initiatives = payload.initiatives
    strategy_graph = payload.strategy_graph

    kpi_user_prompt = f"""
Revise a camada de KPIs com rigor e governança.

Retorne apenas JSON válido e compacto.

KPIs:
{json.dumps(kpis, ensure_ascii=False)}
"""
    kpi_data = call_llm_json(KPI_PROMPT, kpi_user_prompt)
    kpi_integrity = KPIIntegrityOutput(**kpi_data)

    portfolio_user_prompt = f"""
Avalie o portfólio estratégico abaixo.

Retorne apenas JSON válido e compacto.

Temas estratégicos:
{json.dumps(framing.get("strategic_themes", []), ensure_ascii=False)}

Contradições:
{json.dumps(framing.get("contradictions", []), ensure_ascii=False)}

Outcomes:
{json.dumps(outcomes, ensure_ascii=False)}

KPIs:
{json.dumps(kpis, ensure_ascii=False)}

Iniciativas:
{json.dumps(initiatives, ensure_ascii=False)}

Strategy graph:
{json.dumps(strategy_graph, ensure_ascii=False)}
"""
    portfolio_data = call_llm_json(PORTFOLIO_PROMPT, portfolio_user_prompt)
    portfolio = PortfolioOutput(**portfolio_data)

    narrative_user_prompt = f"""
Escreva a narrativa executiva com base nos elementos abaixo.

Retorne apenas JSON válido e compacto.

Framing:
{json.dumps(framing, ensure_ascii=False)}

Outcomes:
{json.dumps(outcomes, ensure_ascii=False)}

KPIs:
{json.dumps(kpis, ensure_ascii=False)}

Iniciativas:
{json.dumps(initiatives, ensure_ascii=False)}

KPI Integrity:
{json.dumps(kpi_integrity.model_dump(), ensure_ascii=False)}

Portfolio:
{json.dumps(portfolio.model_dump(), ensure_ascii=False)}
"""
    narrative_data = call_llm_json(NARRATIVE_PROMPT, narrative_user_prompt)
    narrative = NarrativeOutput(**narrative_data)

    review_result = {
        "kpi_integrity": kpi_integrity.model_dump(),
        "portfolio": portfolio.model_dump(),
        "narrative": narrative.model_dump(),
    }

    score = calculate_strategy_score(
        core_result={
            "framing": framing,
            "mapping": {
                "outcomes": outcomes,
                "kpis": kpis,
                "initiatives": initiatives,
                "strategy_graph": strategy_graph,
            },
        },
        review_result=review_result,
    )

    review_result["strategy_score"] = score
    return review_result


# =========================================================
# FULL ORCHESTRATION
# =========================================================
def run_full_strategy_analysis(payload: StrategyInput):
    framing_result = generate_strategy_framing(payload)
    framing = framing_result["framing"]

    outcomes_kpis_payload = StrategyOutcomesKPIsInput(
        framing=framing,
        company_name=payload.company_name,
        company_context=payload.company_context,
        annual_plan_text=payload.annual_plan_text,
        financial_model_text=payload.financial_model_text,
        market_analysis_text=payload.market_analysis_text,
        leadership_notes_text=payload.leadership_notes_text,
        kpi_targets_text=payload.kpi_targets_text,
        scenario_assumptions_text=payload.scenario_assumptions_text,
        industry_reports_text=payload.industry_reports_text,
        competitor_landscape_text=payload.competitor_landscape_text,
        market_benchmarks_text=payload.market_benchmarks_text,
        customer_research_text=payload.customer_research_text,
        performance_constraints_text=payload.performance_constraints_text,
        performance_constraints=payload.performance_constraints,
    )
    outcomes_kpis_result = generate_strategy_outcomes_kpis(outcomes_kpis_payload)
    outcomes = outcomes_kpis_result["outcomes"]
    kpis = outcomes_kpis_result["kpis"]

    initiatives_payload = StrategyInitiativesInput(
        framing=framing,
        outcomes=outcomes,
        kpis=kpis,
        company_name=payload.company_name,
        company_context=payload.company_context,
        annual_plan_text=payload.annual_plan_text,
        financial_model_text=payload.financial_model_text,
        market_analysis_text=payload.market_analysis_text,
        leadership_notes_text=payload.leadership_notes_text,
        kpi_targets_text=payload.kpi_targets_text,
        scenario_assumptions_text=payload.scenario_assumptions_text,
        industry_reports_text=payload.industry_reports_text,
        competitor_landscape_text=payload.competitor_landscape_text,
        market_benchmarks_text=payload.market_benchmarks_text,
        customer_research_text=payload.customer_research_text,
        performance_constraints_text=payload.performance_constraints_text,
        performance_constraints=payload.performance_constraints,
    )
    initiatives_result = generate_strategy_initiatives(initiatives_payload)
    initiatives = initiatives_result["initiatives"]
    strategy_graph = initiatives_result["strategy_graph"]

    review_payload = StrategyReviewInput(
        framing=framing,
        outcomes=outcomes,
        kpis=kpis,
        initiatives=initiatives,
        strategy_graph=strategy_graph,
        performance_constraints=payload.performance_constraints,
    )
    review_result = generate_strategy_review(review_payload)

    executive_summary = build_executive_summary(
        payload=payload,
        framing=framing,
        outcomes=outcomes,
        kpis=kpis,
        initiatives=initiatives,
        review=review_result,
    )

    return {
        "framing": framing,
        "outcomes": outcomes,
        "kpis": kpis,
        "initiatives": initiatives,
        "strategy_graph": strategy_graph,
        "kpi_integrity": review_result["kpi_integrity"],
        "portfolio": review_result["portfolio"],
        "narrative": review_result["narrative"],
        "strategy_score": review_result["strategy_score"],
        "executive_summary": executive_summary,
    }