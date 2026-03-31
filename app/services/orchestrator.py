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


OUTCOME_KPI_REPAIR_PROMPT = """
Você é um estrategista sênior especialista em modelagem de KPI hierarchy.

Seu trabalho é corrigir apenas outcomes e KPIs problemáticos.

OBJETIVO:
Dado um conjunto pequeno de outcomes com KPI(s) ruins ou incompletos, gere uma versão corrigida e executável.

REGRAS:
- Retorne apenas JSON válido
- Não inclua markdown
- Não inclua comentários
- Não inclua texto fora do JSON
- Todos os campos textuais devem ser strings
- Para cada outcome recebido, gere:
  - exatamente 1 KPI lagging principal
  - entre 2 e 4 KPIs leading
- O KPI lagging deve ter:
  - type = "lagging"
  - level = "north_star"
  - parent_kpi = null
- Os leading devem ter:
  - type = "leading"
  - level = "driver"
  - parent_kpi = nome do KPI lagging principal
- Não usar placeholders como:
  - KPI Principal
  - Definir fórmula
  - Definir formula
  - A definir
  - Indicador principal
- Fórmulas devem ser concretas
- Owners devem ser áreas reais
- Source deve ser concreta
- linked_outcomes deve conter o outcome correto

FORMATO:
{
  "kpis": [
    {
      "name": "...",
      "type": "lagging",
      "level": "north_star",
      "linked_outcomes": ["..."],
      "parent_kpi": null,
      "target": "...",
      "owner": "...",
      "formula": "...",
      "source": "..."
    }
  ]
}
"""


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


def _truncate_text(text: str, limit: int = 6000) -> str:
    text = str(text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...[contexto truncado]"


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
# CONTEXTO
# =========================================================
def build_outcomes_kpis_context(payload) -> str:
    parts = [
        payload.company_context,
        payload.financial_model_text,
        payload.kpi_targets_text,
        payload.leadership_notes_text,
        payload.performance_constraints_text,
        payload.customer_research_text,
    ]
    return "\n\n".join([str(p).strip() for p in parts if p and str(p).strip()])


def build_repair_context(payload, outcome_names: list[str]) -> str:
    text = build_outcomes_kpis_context(payload)
    text = _truncate_text(text, 3000)
    joined = ", ".join(outcome_names)
    return f"Outcomes a corrigir: {joined}\n\nContexto relevante:\n{text}"


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

        linked_theme = str(outcome.get("linked_theme", "")).strip()
        target = str(outcome.get("target", "")).strip()
        timeframe = str(outcome.get("timeframe", "")).strip() or "12 meses"
        value_driver = str(outcome.get("value_driver", "")).strip() or "receita"

        normalized_outcomes.append(
            {
                "name": name,
                "linked_theme": linked_theme,
                "target": target,
                "timeframe": timeframe,
                "value_driver": value_driver,
            }
        )
        outcome_names.add(name)

    normalized_kpis = []
    kpi_names = set()

    for kpi in data["kpis"]:
        if not isinstance(kpi, dict):
            continue

        name = str(kpi.get("name", "")).strip()
        if not name:
            continue

        raw_type = str(kpi.get("type", "")).strip().lower()
        kpi_type = "lagging" if "lag" in raw_type else "leading"

        raw_level = str(kpi.get("level", "")).strip().lower()
        if "north" in raw_level:
            level = "north_star"
        elif "support" in raw_level:
            level = "supporting"
        else:
            level = "driver"

        linked_outcomes = _dict_values_as_list(kpi.get("linked_outcomes", []))
        if isinstance(linked_outcomes, str):
            linked_outcomes = [linked_outcomes]

        linked_outcomes = [
            str(x).strip() for x in linked_outcomes
            if str(x).strip() in outcome_names
        ]

        parent_kpi = kpi.get("parent_kpi")
        parent_kpi = str(parent_kpi).strip() if parent_kpi is not None else None

        item = {
            "name": name,
            "type": kpi_type,
            "level": level,
            "linked_outcomes": linked_outcomes,
            "parent_kpi": parent_kpi if parent_kpi else None,
            "target": str(kpi.get("target", "")).strip() or "",
            "owner": str(kpi.get("owner", "")).strip() or "Estratégia",
            "formula": str(kpi.get("formula", "")).strip() or "Definir fórmula",
            "source": str(kpi.get("source", "")).strip() or "Fonte a definir",
        }

        normalized_kpis.append(item)
        kpi_names.add(name)

    for kpi in normalized_kpis:
        if kpi["parent_kpi"] and kpi["parent_kpi"] not in kpi_names:
            kpi["parent_kpi"] = None

    data["outcomes"] = normalized_outcomes
    data["kpis"] = normalized_kpis
    return data


def merge_kpi_candidates(kpi_groups: list[list[dict]]) -> list[dict]:
    merged = {}

    for group in kpi_groups:
        for kpi in group:
            key = str(kpi.get("name", "")).strip().lower()
            if not key:
                continue

            if key not in merged:
                merged[key] = dict(kpi)
                continue

            existing = merged[key]
            existing_outcomes = set(existing.get("linked_outcomes", []))
            new_outcomes = set(kpi.get("linked_outcomes", []))
            existing["linked_outcomes"] = sorted(existing_outcomes.union(new_outcomes))

            if not existing.get("parent_kpi") and kpi.get("parent_kpi"):
                existing["parent_kpi"] = kpi.get("parent_kpi")

            if existing.get("type") != "lagging" and kpi.get("type") == "lagging":
                existing["type"] = "lagging"

            if existing.get("level") != "north_star" and kpi.get("level") == "north_star":
                existing["level"] = "north_star"

            if str(existing.get("formula", "")).strip().lower() in {"", "definir fórmula", "definir formula", "a definir"}:
                existing["formula"] = kpi.get("formula", existing.get("formula"))

            if str(existing.get("source", "")).strip().lower() in {"", "fonte a definir", "a definir"}:
                existing["source"] = kpi.get("source", existing.get("source"))

            if str(existing.get("owner", "")).strip().lower() in {"", "estratégia", "estrategia"}:
                existing["owner"] = kpi.get("owner", existing.get("owner"))

    return list(merged.values())


def enrich_kpi_quality(kpis: list) -> list:
    fixed = []

    for kpi in kpis:
        item = dict(kpi)
        flags = []

        name = str(item.get("name", "")).strip().lower()
        owner = str(item.get("owner", "")).strip().lower()
        formula = str(item.get("formula", "")).strip().lower()
        source = str(item.get("source", "")).strip().lower()

        if not formula or formula in {"definir fórmula", "definir formula", "a definir", "definir fórmula operacional"}:
            flags.append("missing_formula")

        if not source or source in {"fonte a definir", "a definir", "definir fonte"}:
            flags.append("generic_source")

        if not owner or owner in {"estratégia", "estrategia", "área responsável", "area responsavel"}:
            flags.append("generic_owner")

        if "kpi principal" in name:
            flags.append("auto_generated_kpi")

        if "resultado principal de" in name:
            flags.append("placeholder_kpi")

        score = 100
        if "missing_formula" in flags:
            score -= 30
        if "generic_source" in flags:
            score -= 20
        if "generic_owner" in flags:
            score -= 15
        if "placeholder_kpi" in flags:
            score -= 20
        if "auto_generated_kpi" in flags:
            score -= 10

        item["quality_flags"] = flags
        item["quality_score"] = max(score, 0)
        fixed.append(item)

    return fixed


def build_fallback_kpis_for_outcome(outcome: dict) -> list:
    outcome_name = str(outcome.get("name", "")).strip()
    theme_name = str(outcome.get("linked_theme", "")).strip()
    text = f"{outcome_name} {theme_name}".lower()

    if any(word in text for word in ["receita", "recorrente", "assinatura", "clube"]):
        root = "Receita recorrente mensal do clube (MRR)"
        return [
            {
                "name": root,
                "type": "lagging",
                "level": "north_star",
                "linked_outcomes": [outcome_name],
                "parent_kpi": None,
                "target": outcome.get("target", "") or "Aumentar MRR em 12 meses",
                "owner": "Head do Clube de Assinatura",
                "formula": "Soma da receita mensal recorrente de todos os assinantes ativos",
                "source": "Sistema financeiro e plataforma de assinaturas",
            },
            {
                "name": "Número de assinantes ativos",
                "type": "leading",
                "level": "driver",
                "linked_outcomes": [outcome_name],
                "parent_kpi": root,
                "target": "Expandir base ativa",
                "owner": "Marketing e Vendas",
                "formula": "Contagem de assinantes com assinatura ativa no mês",
                "source": "CRM Clube de Assinatura",
            },
            {
                "name": "Ticket médio por assinante",
                "type": "leading",
                "level": "driver",
                "linked_outcomes": [outcome_name],
                "parent_kpi": root,
                "target": "Elevar ticket médio",
                "owner": "Produto e Marketing",
                "formula": "Receita recorrente mensal / Número de assinantes ativos",
                "source": "Sistema de faturamento e CRM",
            },
            {
                "name": "Taxa de conversão para assinatura",
                "type": "leading",
                "level": "driver",
                "linked_outcomes": [outcome_name],
                "parent_kpi": root,
                "target": "Melhorar conversão",
                "owner": "Marketing Digital",
                "formula": "Número de novos assinantes / Número total de leads qualificados",
                "source": "CRM e plataforma de leads",
            },
        ]

    if any(word in text for word in ["churn", "retenção", "retencao", "renovação", "renovacao"]):
        root = "Taxa de churn mensal do clube de assinatura"
        return [
            {
                "name": root,
                "type": "lagging",
                "level": "north_star",
                "linked_outcomes": [outcome_name],
                "parent_kpi": None,
                "target": outcome.get("target", "") or "Reduzir churn mensal",
                "owner": "Time de Customer Success",
                "formula": "Número de cancelamentos mensais / Número de assinantes ativos no início do mês",
                "source": "CRM Clube de Assinatura",
            },
            {
                "name": "Taxa de renovação mensal do clube",
                "type": "leading",
                "level": "driver",
                "linked_outcomes": [outcome_name],
                "parent_kpi": root,
                "target": "Elevar renovação",
                "owner": "Time de Customer Success",
                "formula": "Número de assinantes que renovaram / Número de assinantes elegíveis para renovação",
                "source": "CRM Clube de Assinatura",
            },
            {
                "name": "Engajamento da base ativa (uso de benefícios e participação)",
                "type": "leading",
                "level": "driver",
                "linked_outcomes": [outcome_name],
                "parent_kpi": root,
                "target": "Elevar uso dos benefícios",
                "owner": "Time de Customer Success",
                "formula": "Percentual de assinantes ativos que usam benefícios e participam de ações",
                "source": "Sistema de CRM e plataforma de eventos",
            },
            {
                "name": "Satisfação média do assinante do clube",
                "type": "leading",
                "level": "driver",
                "linked_outcomes": [outcome_name],
                "parent_kpi": root,
                "target": "NPS >= 70",
                "owner": "Customer Success",
                "formula": "Cálculo de NPS via pesquisa periódica",
                "source": "Pesquisa de satisfação",
            },
        ]

    if any(word in text for word in ["estoque", "capital", "giro", "margem"]):
        root = "Capital empatado em estoque"
        return [
            {
                "name": root,
                "type": "lagging",
                "level": "north_star",
                "linked_outcomes": [outcome_name],
                "parent_kpi": None,
                "target": outcome.get("target", "") or "Reduzir capital empatado",
                "owner": "Controladoria",
                "formula": "Valor total do estoque em caixa",
                "source": "Sistema de gestão de estoque e ERP",
            },
            {
                "name": "Giro de estoque",
                "type": "leading",
                "level": "driver",
                "linked_outcomes": [outcome_name],
                "parent_kpi": root,
                "target": "Elevar giro",
                "owner": "Gestão de Estoque",
                "formula": "Custo das mercadorias vendidas anual / Estoque médio anual",
                "source": "ERP e relatórios financeiros",
            },
            {
                "name": "Dias de estoque",
                "type": "leading",
                "level": "driver",
                "linked_outcomes": [outcome_name],
                "parent_kpi": root,
                "target": "Reduzir dias de estoque",
                "owner": "Gestão de Estoque",
                "formula": "Estoque médio / Custo das mercadorias vendidas diário",
                "source": "ERP e sistema de gestão de estoque",
            },
            {
                "name": "Percentual de estoque parado",
                "type": "leading",
                "level": "driver",
                "linked_outcomes": [outcome_name],
                "parent_kpi": root,
                "target": "Reduzir estoque parado",
                "owner": "Gestão de Estoque",
                "formula": "Estoque parado / Estoque total",
                "source": "Sistema de gestão de estoque",
            },
        ]

    if any(word in text for word in ["comercial", "crm", "digital", "produtividade", "upsell"]):
        root = "Produtividade comercial (receita por vendedor)"
        return [
            {
                "name": root,
                "type": "lagging",
                "level": "north_star",
                "linked_outcomes": [outcome_name],
                "parent_kpi": None,
                "target": outcome.get("target", "") or "Elevar produtividade comercial",
                "owner": "Gerência Comercial",
                "formula": "Receita total / Número de vendedores",
                "source": "ERP e sistema comercial",
            },
            {
                "name": "Adoção do CRM e automação",
                "type": "leading",
                "level": "driver",
                "linked_outcomes": [outcome_name],
                "parent_kpi": root,
                "target": "90% dos vendedores usando CRM",
                "owner": "Operações e TI",
                "formula": "Percentual de vendedores com uso ativo do CRM",
                "source": "Sistema CRM",
            },
            {
                "name": "Número de ações automatizadas de marketing",
                "type": "leading",
                "level": "driver",
                "linked_outcomes": [outcome_name],
                "parent_kpi": root,
                "target": "Expandir campanhas automatizadas",
                "owner": "Marketing",
                "formula": "Contagem de campanhas automatizadas enviadas",
                "source": "Plataformas de automação",
            },
            {
                "name": "Taxa de conversão de leads",
                "type": "leading",
                "level": "driver",
                "linked_outcomes": [outcome_name],
                "parent_kpi": root,
                "target": "Melhorar conversão",
                "owner": "Marketing Digital",
                "formula": "Número de clientes / Número de leads",
                "source": "CRM",
            },
        ]

    if any(word in text for word in ["comunidade", "engajamento", "experiência", "experiencia", "eventos"]):
        root = "Participação ativa da base em eventos e comunidade"
        return [
            {
                "name": root,
                "type": "lagging",
                "level": "north_star",
                "linked_outcomes": [outcome_name],
                "parent_kpi": None,
                "target": outcome.get("target", "") or "Elevar participação da base",
                "owner": "Marketing de Experiências",
                "formula": "Número de membros ativos em eventos e comunidade / Base elegível total",
                "source": "CRM, plataforma de eventos e comunidade",
            },
            {
                "name": "Taxa de participação em eventos exclusivos",
                "type": "leading",
                "level": "driver",
                "linked_outcomes": [outcome_name],
                "parent_kpi": root,
                "target": "Elevar participação por evento",
                "owner": "Marketing de Experiências",
                "formula": "Participantes confirmados / Convites enviados para eventos exclusivos",
                "source": "Plataforma de eventos e CRM",
            },
            {
                "name": "Frequência de interação na comunidade",
                "type": "leading",
                "level": "driver",
                "linked_outcomes": [outcome_name],
                "parent_kpi": root,
                "target": "Aumentar interações mensais",
                "owner": "Comunidade e Conteúdo",
                "formula": "Total de interações mensais na comunidade / Número de membros ativos",
                "source": "Plataforma de comunidade",
            },
            {
                "name": "Taxa de recorrência em eventos",
                "type": "leading",
                "level": "driver",
                "linked_outcomes": [outcome_name],
                "parent_kpi": root,
                "target": "Aumentar recorrência",
                "owner": "Marketing de Experiências",
                "formula": "Número de participantes recorrentes em eventos / Número total de participantes no período",
                "source": "Plataforma de eventos e CRM",
            },
        ]

    return [
        {
            "name": f"Resultado principal de {outcome_name}",
            "type": "lagging",
            "level": "north_star",
            "linked_outcomes": [outcome_name],
            "parent_kpi": None,
            "target": outcome.get("target", "") or "Evoluir resultado",
            "owner": "Área responsável",
            "formula": "Definir fórmula operacional",
            "source": "Definir fonte",
        }
    ]


def enforce_outcome_kpi_coverage(outcomes: list, kpis: list) -> list:
    kpis_by_outcome = defaultdict(list)

    for kpi in kpis:
        for outcome_name in kpi.get("linked_outcomes", []):
            kpis_by_outcome[outcome_name].append(kpi)

    fixed_kpis = list(kpis)

    for outcome in outcomes:
        outcome_name = outcome["name"]
        existing = kpis_by_outcome.get(outcome_name, [])

        if existing:
            continue

        fixed_kpis.extend(build_fallback_kpis_for_outcome(outcome))

    return fixed_kpis


def enforce_kpi_hierarchy(outcomes: list, kpis: list) -> list:
    by_outcome = defaultdict(list)
    for kpi in kpis:
        for outcome_name in kpi.get("linked_outcomes", []):
            by_outcome[outcome_name].append(kpi)

    fixed = []
    seen_keys = set()

    for outcome in outcomes:
        outcome_name = outcome["name"]
        group = by_outcome.get(outcome_name, [])

        if not group:
            continue

        lagging_roots = [
            k for k in group
            if k.get("type") == "lagging" and not k.get("parent_kpi")
        ]

        if not lagging_roots:
            lagging_candidates = [k for k in group if k.get("type") == "lagging"]
            if lagging_candidates:
                lagging_candidates[0]["parent_kpi"] = None
                lagging_roots = [lagging_candidates[0]]
            else:
                group[0]["type"] = "lagging"
                group[0]["level"] = "north_star"
                group[0]["parent_kpi"] = None
                lagging_roots = [group[0]]

        root_name = lagging_roots[0]["name"]

        for k in group:
            item = dict(k)

            if item["name"] == root_name:
                item["level"] = "north_star"
                item["parent_kpi"] = None
                item["type"] = "lagging"
            else:
                item["type"] = "leading"
                if not item.get("parent_kpi"):
                    item["parent_kpi"] = root_name
                if item.get("level") == "north_star":
                    item["level"] = "driver"

            key = (item["name"].strip().lower(), tuple(sorted(item.get("linked_outcomes", []))))
            if key not in seen_keys:
                fixed.append(item)
                seen_keys.add(key)

    return fixed


def classify_weak_outcomes(outcomes: list, kpis: list) -> list[dict]:
    by_outcome = defaultdict(list)
    for kpi in kpis:
        for outcome_name in kpi.get("linked_outcomes", []):
            by_outcome[outcome_name].append(kpi)

    weak = []

    for outcome in outcomes:
        group = by_outcome.get(outcome["name"], [])
        if not group:
            weak.append(outcome)
            continue

        lagging_roots = [k for k in group if k.get("type") == "lagging" and not k.get("parent_kpi")]
        leading = [k for k in group if k.get("type") == "leading"]

        has_bad_formula = any(
            str(k.get("formula", "")).strip().lower() in {"", "definir fórmula", "definir formula", "a definir", "definir fórmula operacional"}
            for k in group
        )
        has_bad_source = any(
            str(k.get("source", "")).strip().lower() in {"", "fonte a definir", "a definir", "definir fonte"}
            for k in group
        )
        has_bad_owner = any(
            str(k.get("owner", "")).strip().lower() in {"", "estratégia", "estrategia", "área responsável", "area responsavel"}
            for k in group
        )
        has_placeholder_name = any(
            "kpi principal" in str(k.get("name", "")).strip().lower() or
            "resultado principal de" in str(k.get("name", "")).strip().lower()
            for k in group
        )

        if len(lagging_roots) != 1:
            weak.append(outcome)
            continue

        if len(leading) < 2:
            weak.append(outcome)
            continue

        if has_bad_formula or has_bad_source or has_bad_owner or has_placeholder_name:
            weak.append(outcome)
            continue

    return weak


def repair_weak_outcomes(payload: StrategyOutcomesKPIsInput, outcomes: list, kpis: list) -> list:
    weak_outcomes = classify_weak_outcomes(outcomes, kpis)
    if not weak_outcomes:
        return kpis

    weak_names = {o["name"] for o in weak_outcomes}
    keep = [k for k in kpis if not any(lo in weak_names for lo in k.get("linked_outcomes", []))]

    repair_context = build_repair_context(payload, [o["name"] for o in weak_outcomes])

    user_prompt = f"""
Corrija os outcomes problemáticos abaixo.

Outcomes:
{json.dumps(weak_outcomes, ensure_ascii=False)}

Framing:
{json.dumps(payload.framing, ensure_ascii=False)}

Contexto:
{repair_context}

IMPORTANTE:
- Para outcomes de comunidade/experiência, não use só NPS.
- Para outcomes de produtividade comercial, incluir drivers concretos de adoção, leads ou conversão.
- Para outcomes de estoque, evitar KPI genérico.
- Para outcomes de receita, usar MRR/receita como lagging principal.
"""

    try:
        repaired = call_llm_json(OUTCOME_KPI_REPAIR_PROMPT, user_prompt)
        parsed = normalize_outcomes_kpis({
            "outcomes": outcomes,
            "kpis": repaired.get("kpis", []),
        })
        repaired_kpis = parsed["kpis"]
        if not repaired_kpis:
            fallback = []
            for outcome in weak_outcomes:
                fallback.extend(build_fallback_kpis_for_outcome(outcome))
            repaired_kpis = fallback
    except Exception:
        fallback = []
        for outcome in weak_outcomes:
            fallback.extend(build_fallback_kpis_for_outcome(outcome))
        repaired_kpis = fallback

    merged = merge_kpi_candidates([keep, repaired_kpis])
    merged = enforce_outcome_kpi_coverage(outcomes, merged)
    merged = enforce_kpi_hierarchy(outcomes, merged)
    merged = enrich_kpi_quality(merged)
    return merged


# =========================================================
# INITIATIVES
# =========================================================
def normalize_initiatives(initiatives_data: dict, outcomes: list, kpis: list) -> dict:
    initiatives_data = dict(initiatives_data or {})
    initiatives_data["initiatives"] = _dict_values_as_list(
        initiatives_data.get("initiatives", [])
    )

    outcome_map = {o["name"]: o for o in outcomes}
    outcome_names = set(outcome_map.keys())
    kpi_names = {k["name"] for k in kpis}

    normalized = []
    for item in initiatives_data["initiatives"]:
        if not isinstance(item, dict):
            continue

        name = str(item.get("name", "")).strip()
        if not name:
            continue

        linked_outcome = str(item.get("linked_outcome", "")).strip()
        if linked_outcome not in outcome_names:
            linked_outcome = ""

        linked_theme = str(item.get("linked_theme", "")).strip()
        if linked_outcome and not linked_theme:
            linked_theme = str(outcome_map[linked_outcome].get("linked_theme", "")).strip()

        linked_kpis = _dict_values_as_list(item.get("linked_kpis", []))
        linked_kpis = [str(x).strip() for x in linked_kpis if str(x).strip() in kpi_names]

        normalized.append(
            {
                "name": name,
                "linked_theme": linked_theme,
                "linked_outcome": linked_outcome,
                "linked_kpis": linked_kpis,
                "expected_impact": str(item.get("expected_impact", "")).strip() or "Melhorar execução e capturar resultado de negócio.",
                "expected_kpi_delta": str(item.get("expected_kpi_delta", "")).strip() or "Melhoria mensurável nos KPIs associados.",
                "time_horizon": str(item.get("time_horizon", "")).strip() or "6 meses",
                "owner": str(item.get("owner", "")).strip() or "Estratégia",
                "status": str(item.get("status", "")).strip().lower() or "planejado",
            }
        )

    initiatives_data["initiatives"] = normalized
    return initiatives_data


def _infer_outcome_from_text(initiative: dict, outcomes: list) -> str:
    text = f"{initiative.get('name', '')} {initiative.get('expected_impact', '')} {initiative.get('expected_kpi_delta', '')}".lower()

    best_match = ""
    best_score = 0

    for outcome in outcomes:
        outcome_name = outcome["name"]
        tokens = [t for t in outcome_name.lower().split() if len(t) > 4]
        score = sum(1 for token in tokens if token in text)
        if score > best_score:
            best_score = score
            best_match = outcome_name

    return best_match if best_score > 0 else ""


def _pick_best_kpis_for_outcome(kpis: list, outcome_name: str, max_items: int = 3) -> list:
    related = [k for k in kpis if outcome_name in k.get("linked_outcomes", [])]
    leading = [k["name"] for k in related if k.get("type") == "leading"]
    lagging = [k["name"] for k in related if k.get("type") == "lagging"]

    picked = leading[:max_items]
    if not picked and lagging:
        picked = lagging[:1]

    return picked[:max_items]


def enforce_initiative_links(outcomes: list, kpis: list, initiatives: list) -> list:
    outcome_map = {o["name"]: o for o in outcomes}
    outcome_names = set(outcome_map.keys())
    all_kpi_names = {k["name"] for k in kpis}

    fixed = []
    for initiative in initiatives:
        item = dict(initiative)

        linked_outcome = str(item.get("linked_outcome", "")).strip()
        if linked_outcome not in outcome_names:
            linked_outcome = _infer_outcome_from_text(item, outcomes)

        if linked_outcome:
            item["linked_outcome"] = linked_outcome

            if not str(item.get("linked_theme", "")).strip():
                item["linked_theme"] = str(outcome_map[linked_outcome].get("linked_theme", "")).strip()

        linked_kpis = [k for k in item.get("linked_kpis", []) if k in all_kpi_names]
        if linked_outcome and not linked_kpis:
            linked_kpis = _pick_best_kpis_for_outcome(kpis, linked_outcome, max_items=3)

        item["linked_kpis"] = linked_kpis
        fixed.append(item)

    return fixed


def ensure_minimum_initiatives_per_outcome(outcomes: list, kpis: list, initiatives: list) -> list:
    by_outcome = defaultdict(list)
    for initiative in initiatives:
        outcome_name = initiative.get("linked_outcome", "")
        if outcome_name:
            by_outcome[outcome_name].append(initiative)

    fixed = list(initiatives)

    for outcome in outcomes:
        outcome_name = outcome["name"]
        theme_name = outcome.get("linked_theme", "")
        current = by_outcome.get(outcome_name, [])

        if len(current) >= 2:
            continue

        linked_kpis = _pick_best_kpis_for_outcome(kpis, outcome_name, max_items=2)

        defaults = [
            {
                "name": f"Estruturar playbook operacional para acelerar {outcome_name.lower()}",
                "linked_theme": theme_name,
                "linked_outcome": outcome_name,
                "linked_kpis": linked_kpis,
                "expected_impact": "Aumentar consistência de execução e capturar resultado de negócio com mais previsibilidade.",
                "expected_kpi_delta": "Melhoria gradual nos principais drivers do outcome.",
                "time_horizon": "6 meses",
                "owner": "Estratégia",
                "status": "planejado",
            },
            {
                "name": f"Implantar rotina de gestão e acompanhamento para sustentar {outcome_name.lower()}",
                "linked_theme": theme_name,
                "linked_outcome": outcome_name,
                "linked_kpis": linked_kpis,
                "expected_impact": "Reduzir dispersão de execução e melhorar governança sobre os indicadores do outcome.",
                "expected_kpi_delta": "Maior estabilidade e evolução dos KPIs vinculados.",
                "time_horizon": "3 meses",
                "owner": "Operações",
                "status": "planejado",
            },
        ]

        existing_names = {i["name"] for i in current}
        current_count = len(current)

        for candidate in defaults:
            if candidate["name"] not in existing_names:
                fixed.append(candidate)
                existing_names.add(candidate["name"])
                current_count += 1
            if current_count >= 2:
                break

    return fixed


def rebuild_strategy_graph(outcomes: list, kpis: list, initiatives: list) -> dict:
    graph = {}
    kpi_map = {k["name"]: k for k in kpis}

    for initiative in initiatives:
        linked_kpis = initiative.get("linked_kpis", [])
        linked_outcome = initiative.get("linked_outcome", "")

        leading = ""
        lagging = ""

        for kpi_name in linked_kpis:
            kpi = kpi_map.get(kpi_name)
            if not kpi:
                continue
            if kpi.get("type") == "leading" and not leading:
                leading = kpi_name
            if kpi.get("type") == "lagging" and not lagging:
                lagging = kpi_name

        if not lagging and linked_outcome:
            for kpi in kpis:
                if linked_outcome in kpi.get("linked_outcomes", []) and kpi.get("type") == "lagging" and not kpi.get("parent_kpi"):
                    lagging = kpi["name"]
                    break

        graph[initiative["name"]] = {
            "kpi_leading": leading,
            "kpi_lagging": lagging,
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
        f"mas o valor vem da qualidade da cascata entre outcomes, KPI hierarchy e iniciativas."
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

    return {"framing": framing.model_dump()}


def generate_strategy_outcomes_kpis(payload: StrategyOutcomesKPIsInput):
    base_context = build_outcomes_kpis_context(payload)
    base_context = _truncate_text(base_context, 5000)

    framing = payload.framing

    user_prompt = f"""
Gere outcomes e KPI hierarchy com ligação causal explícita a partir do framing estratégico.

Framing:
{json.dumps(framing, ensure_ascii=False)}

Materiais originais:
{base_context}

IMPORTANTE:
- Para cada outcome, gerar exatamente 1 KPI lagging principal e 2 a 4 leading.
- Para receita recorrente/clube, o KPI lagging deve ser MRR/receita recorrente.
- Para churn/retenção, o KPI lagging deve ser churn ou retenção/renovação.
- Para estoque/capital de giro, o KPI lagging deve ser capital empatado/valor total do estoque.
- Para produtividade comercial, o KPI lagging deve ser produtividade/receita por vendedor, CAC ou receita incremental.
- Para comunidade/experiência, não usar apenas NPS; incluir participação ativa/recorrência/engajamento como métrica principal ou drivers claros.
- Não usar placeholders como "KPI Principal", "Definir fórmula", "A definir", "Indicador principal".
- Owners devem ser áreas reais.
- Sources devem ser concretas.
"""

    data = call_llm_json(OUTCOMES_KPIS_PROMPT, user_prompt)
    data = normalize_outcomes_kpis(data)
    outcomes = data["outcomes"]
    kpis = data["kpis"]

    kpis = enforce_outcome_kpi_coverage(outcomes, kpis)
    kpis = enforce_kpi_hierarchy(outcomes, kpis)
    kpis = enrich_kpi_quality(kpis)
    kpis = repair_weak_outcomes(payload, outcomes, kpis)

    outcomes_kpis = OutcomesKPIsOutput(
        outcomes=outcomes,
        kpis=kpis,
    )
    return outcomes_kpis.model_dump()


def generate_strategy_initiatives(payload: StrategyInitiativesInput):
    base_context = build_strategy_context_from_mapping_input(payload)
    base_context = _truncate_text(base_context, 9000)
    framing = payload.framing
    outcomes = payload.outcomes
    kpis = payload.kpis

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

IMPORTANTE:
- Todos os outcomes precisam ter iniciativas.
- Gere no mínimo 2 iniciativas por outcome.
- As iniciativas devem parecer cobradas por um executivo real.
- Evite nomes vagos.
- Priorize KPIs leading em linked_kpis.
- Não gere strategy_graph.
"""

    data = call_llm_json(INITIATIVES_PROMPT, user_prompt)
    data = normalize_initiatives(data, outcomes, kpis)
    data["initiatives"] = enforce_initiative_links(outcomes, kpis, data["initiatives"])
    data["initiatives"] = ensure_minimum_initiatives_per_outcome(outcomes, kpis, data["initiatives"])
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