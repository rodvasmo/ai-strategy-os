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
from app.agents.strategy_initiatives_agent import SYSTEM_PROMPT as INITIATIVES_PROMPT
from app.agents.kpi_integrity_agent import SYSTEM_PROMPT as KPI_PROMPT
from app.agents.portfolio_intelligence_agent import SYSTEM_PROMPT as PORTFOLIO_PROMPT
from app.agents.narrative_agent import SYSTEM_PROMPT as NARRATIVE_PROMPT


OUTCOMES_ONLY_PROMPT = """
Você é um estrategista sênior responsável por transformar um framing estratégico em outcomes executivos claros.

Seu papel nesta etapa é gerar SOMENTE outcomes estratégicos.
NÃO gere KPIs.
NÃO gere iniciativas.

OBJETIVO:
Traduzir os strategic_themes em resultados de negócio claros, mensuráveis e úteis para a próxima etapa de KPI hierarchy.

REGRAS:
- Retorne apenas JSON válido
- Não inclua markdown
- Não inclua comentários
- Não inclua texto fora do JSON
- Todos os campos textuais devem ser strings
- Gere entre 1 e 2 outcomes por tema
- Evite outcomes genéricos
- Outcome deve representar resultado de negócio, não ação
- Sempre incluir target, timeframe e value_driver
- linked_theme deve bater exatamente com strategic_theme.name
- Use somente informações do framing e do contexto
- Se faltar detalhe, complete de forma plausível e conservadora
- Não invente geografias, canais, produtos ou frentes não citadas

FORMATO:
{
  "outcomes": [
    {
      "name": "...",
      "linked_theme": "...",
      "target": "...",
      "timeframe": "12 meses",
      "value_driver": "receita"
    }
  ]
}
"""


KPI_PER_OUTCOME_PROMPT = """
Você é um estrategista sênior especializado em modelagem de KPI hierarchy.

Seu trabalho nesta etapa é gerar KPIs para UM outcome específico.

OBJETIVO:
Construir uma hierarquia causal clara:
- 1 KPI lagging principal (north star do outcome)
- 2 a 4 KPIs leading acionáveis
- todos conectados explicitamente ao outcome informado

REGRAS:
- Retorne apenas JSON válido
- Não inclua markdown
- Não inclua comentários
- Não inclua texto fora do JSON
- Todos os campos textuais devem ser strings
- Gere no mínimo 3 KPIs no total
- Deve existir exatamente 1 KPI lagging principal
- Os demais devem ser KPIs leading
- O KPI lagging principal deve ter parent_kpi = null
- Os KPIs leading devem apontar parent_kpi para o KPI lagging principal
- linked_outcomes deve conter o outcome informado
- Fórmulas devem ser concretas
- Owners devem ser áreas reais, não "Estratégia"
- Source deve ser concreta
- Evite placeholders como:
  - KPI Principal
  - Definir fórmula
  - A definir
  - Indicador principal
- Evite repetir o nome do outcome como KPI se isso não for uma métrica real
- KPIs devem ser executáveis e cobrados por um executivo real

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
    },
    {
      "name": "...",
      "type": "leading",
      "level": "driver",
      "linked_outcomes": ["..."],
      "parent_kpi": "...",
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
    return "\n\n".join(
        [str(p).strip() for p in parts if p and str(p).strip()]
    )


def build_outcome_specific_context(payload, outcome: dict) -> str:
    outcome_name = str(outcome.get("name", "")).lower()
    theme_name = str(outcome.get("linked_theme", "")).lower()

    selected = [payload.company_context]

    if any(word in f"{outcome_name} {theme_name}" for word in ["receita", "assinatura", "clube", "churn", "reten"]):
        selected.extend([
            payload.financial_model_text,
            payload.kpi_targets_text,
            payload.customer_research_text,
            payload.leadership_notes_text,
        ])

    elif any(word in f"{outcome_name} {theme_name}" for word in ["estoque", "capital", "giro", "margem"]):
        selected.extend([
            payload.financial_model_text,
            payload.kpi_targets_text,
            payload.leadership_notes_text,
            payload.performance_constraints_text,
        ])

    elif any(word in f"{outcome_name} {theme_name}" for word in ["crm", "digital", "comercial", "upsell", "produtividade"]):
        selected.extend([
            payload.kpi_targets_text,
            payload.leadership_notes_text,
            payload.customer_research_text,
            payload.financial_model_text,
        ])

    elif any(word in f"{outcome_name} {theme_name}" for word in ["comunidade", "engajamento", "experiência", "experiencia", "eventos"]):
        selected.extend([
            payload.customer_research_text,
            payload.leadership_notes_text,
            payload.kpi_targets_text,
            payload.company_context,
        ])

    else:
        selected.extend([
            payload.financial_model_text,
            payload.kpi_targets_text,
            payload.leadership_notes_text,
        ])

    text = "\n\n".join([str(x).strip() for x in selected if x and str(x).strip()])
    return _truncate_text(text, 3500)


# =========================================================
# OUTCOMES + KPI HIERARCHY
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
        if "lag" in raw_type:
            kpi_type = "lagging"
        else:
            kpi_type = "leading"

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


def build_theme_kpi_guidelines(framing: dict) -> str:
    guidelines = []

    for theme in framing.get("strategic_themes", []):
        theme_text = f"{theme.get('name', '')} {theme.get('description', '')}".lower()

        if any(word in theme_text for word in ["estoque", "capital", "giro", "margem"]):
            guidelines.append("""
Para temas de estoque/capital de giro, considere incluir:
- KPI lagging: capital empatado em estoque ou valor total do estoque
- KPIs leading: giro de estoque, dias de estoque, percentual de estoque parado, ruptura de produtos prioritários
- Evite KPI genérico
""")

        if any(word in theme_text for word in ["churn", "retenção", "retencao", "fidelização", "fidelizacao"]):
            guidelines.append("""
Para temas de retenção/churn, considere incluir:
- KPI lagging: churn ou taxa de retenção/renovação
- KPIs leading: NPS/satisfação, uso de benefícios, frequência de compra, engajamento da base
- Não usar apenas NPS; NPS é driver, não resultado final
""")

        if any(word in theme_text for word in ["receita", "recorrência", "recorrencia", "assinatura", "clube"]):
            guidelines.append("""
Para temas de receita recorrente/clube, considere incluir:
- KPI lagging: MRR/receita recorrente
- KPIs leading: base ativa, ticket médio, conversão para assinatura, upgrade/upsell
- Evite misturar KPI de comunidade aqui se o outcome for financeiro
""")

        if any(word in theme_text for word in ["digital", "crm", "automação", "automacao", "comercial", "upsell"]):
            guidelines.append("""
Para temas comerciais/digitais, considere incluir:
- KPI lagging: produtividade comercial, receita por vendedor, receita incremental, CAC
- KPIs leading: adoção de CRM, leads qualificados, conversão, campanhas automatizadas
- Os leading devem ser operacionalizáveis por Marketing/Comercial/TI
""")

        if any(word in theme_text for word in ["comunidade", "engajamento", "experiência", "experiencia", "eventos"]):
            guidelines.append("""
Para temas de comunidade/experiência, considere incluir:
- KPI lagging: participação ativa da base em eventos/comunidade ou retenção da comunidade
- KPIs leading: frequência de participação, interações, recorrência em eventos, adesão a benefícios
- NPS pode existir, mas não deve ser o único KPI
- Evite owner genérico e evite 'kpi principal'
""")

    return "\n".join(sorted(set(guidelines)))


def _pick_theme_by_name(framing: dict, theme_name: str) -> dict:
    for theme in framing.get("strategic_themes", []):
        if str(theme.get("name", "")).strip() == str(theme_name).strip():
            return theme
    return {}


def _theme_keywords(theme_name: str, outcome_name: str) -> str:
    return f"{theme_name} {outcome_name}".lower()


def build_fallback_kpis_for_outcome(outcome: dict, framing: dict) -> list:
    outcome_name = str(outcome.get("name", "")).strip()
    theme_name = str(outcome.get("linked_theme", "")).strip()
    text = _theme_keywords(theme_name, outcome_name)

    if any(word in text for word in ["receita", "recorrente", "assinatura", "clube"]):
        return [
            {
                "name": "Receita recorrente mensal do clube (MRR)",
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
                "parent_kpi": "Receita recorrente mensal do clube (MRR)",
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
                "parent_kpi": "Receita recorrente mensal do clube (MRR)",
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
                "parent_kpi": "Receita recorrente mensal do clube (MRR)",
                "target": "Melhorar conversão",
                "owner": "Marketing Digital",
                "formula": "Número de novos assinantes / Número total de leads qualificados",
                "source": "CRM e plataforma de leads",
            },
        ]

    if any(word in text for word in ["churn", "retenção", "retencao", "renovação", "renovacao"]):
        return [
            {
                "name": "Taxa de churn mensal do clube de assinatura",
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
                "parent_kpi": "Taxa de churn mensal do clube de assinatura",
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
                "parent_kpi": "Taxa de churn mensal do clube de assinatura",
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
                "parent_kpi": "Taxa de churn mensal do clube de assinatura",
                "target": "NPS >= 70",
                "owner": "Customer Success",
                "formula": "Cálculo de NPS via pesquisa periódica",
                "source": "Pesquisa de satisfação",
            },
        ]

    if any(word in text for word in ["estoque", "capital", "giro", "margem"]):
        return [
            {
                "name": "Capital empatado em estoque",
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
                "parent_kpi": "Capital empatado em estoque",
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
                "parent_kpi": "Capital empatado em estoque",
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
                "parent_kpi": "Capital empatado em estoque",
                "target": "Reduzir estoque parado",
                "owner": "Gestão de Estoque",
                "formula": "Estoque parado / Estoque total",
                "source": "Sistema de gestão de estoque",
            },
        ]

    if any(word in text for word in ["comercial", "crm", "digital", "produtividade", "upsell"]):
        return [
            {
                "name": "Produtividade comercial (receita por vendedor)",
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
                "parent_kpi": "Produtividade comercial (receita por vendedor)",
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
                "parent_kpi": "Produtividade comercial (receita por vendedor)",
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
                "parent_kpi": "Produtividade comercial (receita por vendedor)",
                "target": "Melhorar conversão",
                "owner": "Marketing Digital",
                "formula": "Número de clientes / Número de leads",
                "source": "CRM",
            },
        ]

    if any(word in text for word in ["comunidade", "engajamento", "experiência", "experiencia", "eventos"]):
        return [
            {
                "name": "Participação ativa da base em eventos e comunidade",
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
                "parent_kpi": "Participação ativa da base em eventos e comunidade",
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
                "parent_kpi": "Participação ativa da base em eventos e comunidade",
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
                "parent_kpi": "Participação ativa da base em eventos e comunidade",
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


def merge_kpi_candidates(kpi_groups: list) -> list:
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

            if str(existing.get("owner", "")).strip().lower() in {"", "estratégia", "estrategia", "área responsável", "area responsavel"}:
                existing["owner"] = kpi.get("owner", existing.get("owner"))

    return list(merged.values())


def enforce_outcome_kpi_coverage(outcomes: list, kpis: list, framing: dict) -> list:
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

        fixed_kpis.extend(build_fallback_kpis_for_outcome(outcome, framing))

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


def repair_weak_kpis(outcomes: list, kpis: list, framing: dict) -> list:
    by_outcome = defaultdict(list)
    for kpi in kpis:
        for outcome_name in kpi.get("linked_outcomes", []):
            by_outcome[outcome_name].append(kpi)

    repaired = []

    for outcome in outcomes:
        group = by_outcome.get(outcome["name"], [])

        if not group:
            repaired.extend(build_fallback_kpis_for_outcome(outcome, framing))
            continue

        group_quality = min([int(k.get("quality_score", 0)) for k in group]) if group else 0
        bad_placeholder = any(
            "auto_generated_kpi" in k.get("quality_flags", []) or
            "placeholder_kpi" in k.get("quality_flags", []) or
            "missing_formula" in k.get("quality_flags", [])
            for k in group
        )

        if group_quality < 70 or bad_placeholder:
            fallback = build_fallback_kpis_for_outcome(outcome, framing)
            fallback_names = {f["name"].strip().lower() for f in fallback}
            cleaned_group = [
                g for g in group
                if "auto_generated_kpi" not in g.get("quality_flags", [])
                and "placeholder_kpi" not in g.get("quality_flags", [])
            ]

            names_existing = {g["name"].strip().lower() for g in cleaned_group}
            for f in fallback:
                if f["name"].strip().lower() not in names_existing:
                    cleaned_group.append(f)

            repaired.extend(cleaned_group)
        else:
            repaired.extend(group)

    repaired = merge_kpi_candidates([repaired])
    repaired = enforce_kpi_hierarchy(outcomes, repaired)
    repaired = enrich_kpi_quality(repaired)
    return repaired


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


def enforce_initiative_links(outcomes: list, kpis: list, initiatives: list) -> list:
    outcome_names = {o["name"] for o in outcomes}
    kpis_by_outcome = defaultdict(list)

    for kpi in kpis:
        for linked_outcome in kpi.get("linked_outcomes", []):
            kpis_by_outcome[linked_outcome].append(kpi["name"])

    fixed = []
    all_kpi_names = {k["name"] for k in kpis}

    for initiative in initiatives:
        linked_outcome = initiative.get("linked_outcome", "")
        linked_kpis = [k for k in initiative.get("linked_kpis", []) if k in all_kpi_names]

        if linked_outcome not in outcome_names:
            text = f"{initiative.get('name', '')} {initiative.get('expected_impact', '')}".lower()
            for outcome in outcomes:
                tokens = [t for t in outcome["name"].lower().split() if len(t) > 4]
                if any(token in text for token in tokens):
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
            if kpi["type"] == "leading" and not leading:
                leading = kpi_name
            if kpi["type"] == "lagging" and not lagging:
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


def generate_outcomes_only(payload: StrategyOutcomesKPIsInput) -> list:
    base_context = _truncate_text(build_outcomes_kpis_context(payload), 4500)
    framing = payload.framing
    theme_guidelines = build_theme_kpi_guidelines(framing)

    user_prompt = f"""
Gere outcomes estratégicos a partir do framing abaixo.

Framing:
{json.dumps(framing, ensure_ascii=False)}

Contexto:
{base_context}

Diretrizes:
{theme_guidelines}
"""

    data = call_llm_json(OUTCOMES_ONLY_PROMPT, user_prompt)
    data = normalize_outcomes_kpis({"outcomes": data.get("outcomes", []), "kpis": []})
    return data["outcomes"]


def generate_kpis_for_single_outcome(payload: StrategyOutcomesKPIsInput, outcome: dict) -> list:
    framing = payload.framing
    theme = _pick_theme_by_name(framing, outcome.get("linked_theme", ""))
    context = build_outcome_specific_context(payload, outcome)

    user_prompt = f"""
Gere KPIs somente para este outcome.

Outcome:
{json.dumps(outcome, ensure_ascii=False)}

Tema estratégico relacionado:
{json.dumps(theme, ensure_ascii=False)}

Contexto relevante:
{context}

Instruções adicionais:
- O KPI lagging deve refletir o resultado final do outcome.
- Os KPIs leading devem ser acionáveis.
- Não usar placeholders.
- Fórmulas e fontes devem ser concretas.
"""

    try:
        response = call_llm_json(KPI_PER_OUTCOME_PROMPT, user_prompt)
        parsed = normalize_outcomes_kpis({
            "outcomes": [outcome],
            "kpis": response.get("kpis", []),
        })
        kpis = parsed["kpis"]
        if not kpis:
            return build_fallback_kpis_for_outcome(outcome, framing)
        return kpis
    except Exception:
        return build_fallback_kpis_for_outcome(outcome, framing)


def generate_strategy_outcomes_kpis(payload: StrategyOutcomesKPIsInput):
    outcomes = generate_outcomes_only(payload)

    kpi_groups = []
    for outcome in outcomes:
        kpi_groups.append(generate_kpis_for_single_outcome(payload, outcome))

    merged_kpis = merge_kpi_candidates(kpi_groups)
    merged_kpis = enforce_outcome_kpi_coverage(outcomes, merged_kpis, payload.framing)
    merged_kpis = enforce_kpi_hierarchy(outcomes, merged_kpis)
    merged_kpis = enrich_kpi_quality(merged_kpis)
    merged_kpis = repair_weak_kpis(outcomes, merged_kpis, payload.framing)

    data = {
        "outcomes": outcomes,
        "kpis": merged_kpis,
    }

    outcomes_kpis = OutcomesKPIsOutput(**data)
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