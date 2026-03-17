import json

from app.models.schemas import (
    StrategyInput,
    StrategyReviewInput,
    FramingOutput,
    MappingOutput,
    KPIIntegrityOutput,
    PortfolioOutput,
    NarrativeOutput,
)

from app.services.parser import build_strategy_context
from app.services.llm import call_llm_json
from app.services.scoring import calculate_strategy_score

from app.agents.strategy_framing_agent import SYSTEM_PROMPT as FRAMING_PROMPT
from app.agents.strategy_mapping_agent import SYSTEM_PROMPT as MAPPING_PROMPT
from app.agents.kpi_integrity_agent import SYSTEM_PROMPT as KPI_PROMPT
from app.agents.portfolio_intelligence_agent import SYSTEM_PROMPT as PORTFOLIO_PROMPT
from app.agents.narrative_agent import SYSTEM_PROMPT as NARRATIVE_PROMPT


# 🔥 NORMALIZATION LAYER (CRÍTICO)
def normalize_mapping(mapping_data: dict) -> dict:
    # 1. Corrigir targets para string
    for outcome in mapping_data.get("outcomes", []):
        if "target" in outcome:
            outcome["target"] = str(outcome["target"])

    for kpi in mapping_data.get("kpis", []):
        if "target" in kpi:
            kpi["target"] = str(kpi["target"])

    # 2. Corrigir strategy_graph se vier como lista
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
                    "gap": item.get("gap", "")
                }
        mapping_data["strategy_graph"] = fixed_graph

    return mapping_data


# =========================
# CORE GENERATION
# =========================
def generate_strategy_core(payload: StrategyInput):
    base_context = build_strategy_context(payload)

    # STEP 1 — Strategy Framing
    framing_user_prompt = f"""
Analise os materiais estratégicos abaixo e construa o framing estratégico.

Retorne apenas JSON válido e compacto.

Materiais:
{base_context}
"""
    framing_data = call_llm_json(FRAMING_PROMPT, framing_user_prompt)
    framing = FramingOutput(**framing_data)

    # STEP 2 — Strategy Mapping
    mapping_user_prompt = f"""
Construa o modelo executável da estratégia.

IMPORTANTE:
- siga exatamente o formato exigido no system prompt
- não crie campos extras
- use apenas os campos permitidos
- todo outcome deve ter linked_theme
- todo KPI deve ter type
- toda iniciativa deve ter name e linked_theme
- retorne apenas JSON válido e compacto

Regras adicionais obrigatórias:
- todo outcome deve ter pelo menos uma iniciativa
- toda iniciativa deve ter KPI leading associado
- nenhuma iniciativa pode ficar fora do strategy_graph
- não deixe lacunas de cobertura
- seja específico e quantitativo

Framing estratégico:
{json.dumps(framing.model_dump(), ensure_ascii=False)}

Materiais originais:
{base_context}
"""
    mapping_data = call_llm_json(MAPPING_PROMPT, mapping_user_prompt)

    # 🔥 NORMALIZAÇÃO (CRÍTICO)
    mapping_data = normalize_mapping(mapping_data)

    mapping = MappingOutput(**mapping_data)

    return {
        "framing": framing.model_dump(),
        "mapping": mapping.model_dump()
    }


# =========================
# REVIEW
# =========================
def generate_strategy_review(payload: StrategyReviewInput):
    framing = payload.framing
    mapping = payload.mapping

    # STEP 3 — KPI Integrity
    kpi_user_prompt = f"""
Revise a camada de KPIs com rigor e governança.

Retorne apenas JSON válido e compacto.

KPIs:
{json.dumps(mapping.get("kpis", []), ensure_ascii=False)}
"""
    kpi_data = call_llm_json(KPI_PROMPT, kpi_user_prompt)
    kpi_integrity = KPIIntegrityOutput(**kpi_data)

    # STEP 4 — Portfolio Intelligence
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

    # STEP 5 — Narrative
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
        "narrative": narrative.model_dump()
    }

    score = calculate_strategy_score(
        core_result={
            "framing": framing,
            "mapping": mapping
        },
        review_result=review_result
    )

    review_result["strategy_score"] = score

    return review_result