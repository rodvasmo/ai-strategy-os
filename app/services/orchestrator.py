import ast
import json

from app.models.schemas import (
    StrategyInput,
    StrategyMappingInput,
    StrategyReviewInput,
    FramingOutput,
    MappingOutput,
    KPIIntegrityOutput,
    PortfolioOutput,
    NarrativeOutput,
)
from app.services.parser import (
    build_strategy_context,
    build_strategy_context_from_mapping_input,
)
from app.services.llm import call_llm_json
from app.services.scoring import calculate_strategy_score

from app.agents.strategy_framing_agent import SYSTEM_PROMPT as FRAMING_PROMPT
from app.agents.strategy_mapping_agent import SYSTEM_PROMPT as MAPPING_PROMPT
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
Você é um estrategista sênior e deve COMPLETAR um framing estratégico incompleto.

Regras obrigatórias:
- strategic_themes deve ser LISTA
- assumptions deve ser LISTA de strings com no mínimo 3 itens
- contradictions deve ser LISTA de strings com no mínimo 2 itens
- cada theme deve conter:
  - name
  - description
  - where_to_play
  - how_to_win
  - economic_logic
  - tradeoffs
  - not_doing
  - constraints

Preserve o que estiver bom.
Complete o que estiver faltando.
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
            "A base de clientes responderá positivamente a recorrência e conteúdo."
        ]

    if len(repaired.get("contradictions", [])) < 2:
        repaired["contradictions"] = repaired.get("contradictions", []) + [
            "A empresa busca crescer rapidamente, mas enfrenta pressão de margem e capital empatado.",
            "A construção do ecossistema aumenta diferenciação, mas também aumenta complexidade operacional."
        ]

    repaired["assumptions"] = repaired["assumptions"][:6]
    repaired["contradictions"] = repaired["contradictions"][:4]

    return repaired


# =========================================================
# MAPPING
# =========================================================
def normalize_mapping(mapping_data: dict) -> dict:
    mapping_data = dict(mapping_data or {})

    mapping_data["outcomes"] = _dict_values_as_list(mapping_data.get("outcomes", []))
    mapping_data["kpis"] = _dict_values_as_list(mapping_data.get("kpis", []))
    mapping_data["initiatives"] = _dict_values_as_list(mapping_data.get("initiatives", []))

    for outcome in mapping_data.get("outcomes", []):
        if "target" in outcome and outcome["target"] is not None:
            outcome["target"] = str(outcome["target"])

    for kpi in mapping_data.get("kpis", []):
        if "target" in kpi and kpi["target"] is not None:
            kpi["target"] = str(kpi["target"])

    graph = mapping_data.get("strategy_graph")
    if isinstance(graph, list):
        fixed_graph = {}
        for item in graph:
            name = item.get("initiative") or item.get("name")
            if name:
                fixed_graph[name] = {
                    "kpi_leading": item.get("kpi_leading", ""),
                    "kpi_lagging": item.get("kpi_lagging", ""),
                    "outcome": item.get("outcome", ""),
                    "causal_logic": item.get("causal_logic", "") or item.get("gap", ""),
                }
        mapping_data["strategy_graph"] = fixed_graph

    if graph is None or not isinstance(mapping_data.get("strategy_graph"), dict):
        mapping_data["strategy_graph"] = {}

    return mapping_data


# =========================================================
# EXECUTIVE SUMMARY
# =========================================================
def build_executive_summary(
    payload: StrategyInput,
    framing: dict,
    mapping: dict,
    review: dict,
) -> dict:
    strategy_score = review.get("strategy_score", {})
    portfolio = review.get("portfolio", {})
    narrative = review.get("narrative", {})

    company_name = payload.company_name or "Empresa"

    top_insights = [
        narrative.get("executive_summary", ""),
    ]

    for item in narrative.get("key_risks", [])[:2]:
        top_insights.append(item)

    priority_actions = []
    for rec in narrative.get("recommendations", [])[:4]:
        action = rec.get("action", "")
        if action:
            priority_actions.append(action)

    key_metrics = []
    for outcome in mapping.get("outcomes", [])[:4]:
        key_metrics.append(f"{outcome.get('name')}: {outcome.get('target')}")

    headline = (
        f"{company_name}: crescimento e recorrência têm potencial relevante, "
        f"mas eficiência operacional e governança de métricas limitam a captura de valor."
    )

    final_takeaway = (
        f"Score estratégico atual: {strategy_score.get('overall_score', 'n/a')}. "
        "A direção estratégica faz sentido, mas a priorização de capital e a integridade dos KPIs "
        "precisam melhorar para sustentar crescimento com rentabilidade."
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
    base_context = build_strategy_context(payload)

    framing_user_prompt = f"""
Analise os materiais estratégicos abaixo e construa o framing estratégico.

Retorne apenas JSON válido e compacto.

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


def generate_strategy_mapping(payload: StrategyMappingInput):
    base_context = build_strategy_context_from_mapping_input(payload)
    framing = payload.framing

    mapping_user_prompt = f"""
Construa o modelo executável da estratégia.

Retorne apenas JSON válido e compacto.

Framing estratégico:
{json.dumps(framing, ensure_ascii=False)}

Materiais originais:
{base_context}
"""
    mapping_data = call_llm_json(MAPPING_PROMPT, mapping_user_prompt)
    mapping_data = normalize_mapping(mapping_data)
    mapping = MappingOutput(**mapping_data)

    return {
        "mapping": mapping.model_dump()
    }


def generate_strategy_review(payload: StrategyReviewInput):
    framing = payload.framing
    mapping = payload.mapping

    kpi_user_prompt = f"""
Revise a camada de KPIs com rigor e governança.

Retorne apenas JSON válido e compacto.

KPIs:
{json.dumps(mapping.get("kpis", []), ensure_ascii=False)}
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
{json.dumps(mapping.get("outcomes", []), ensure_ascii=False)}

KPIs:
{json.dumps(mapping.get("kpis", []), ensure_ascii=False)}

Iniciativas:
{json.dumps(mapping.get("initiatives", []), ensure_ascii=False)}

Strategy graph:
{json.dumps(mapping.get("strategy_graph", {}), ensure_ascii=False)}
"""
    portfolio_data = call_llm_json(PORTFOLIO_PROMPT, portfolio_user_prompt)
    portfolio = PortfolioOutput(**portfolio_data)

    narrative_user_prompt = f"""
Escreva a narrativa executiva com base nos elementos abaixo.

Retorne apenas JSON válido e compacto.

Framing:
{json.dumps(framing, ensure_ascii=False)}

Mapping:
{json.dumps(mapping, ensure_ascii=False)}

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
            "mapping": mapping,
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

    mapping_payload = StrategyMappingInput(
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
    )

    mapping_result = generate_strategy_mapping(mapping_payload)
    mapping = mapping_result["mapping"]

    review_payload = StrategyReviewInput(
        framing=framing,
        mapping=mapping,
    )

    review_result = generate_strategy_review(review_payload)

    executive_summary = build_executive_summary(
        payload=payload,
        framing=framing,
        mapping=mapping,
        review=review_result,
    )

    return {
        "framing": framing,
        "mapping": mapping,
        "kpi_integrity": review_result["kpi_integrity"],
        "portfolio": review_result["portfolio"],
        "narrative": review_result["narrative"],
        "strategy_score": review_result["strategy_score"],
        "executive_summary": executive_summary,
    }