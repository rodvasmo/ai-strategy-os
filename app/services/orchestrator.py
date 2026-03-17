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


def generate_strategy_framing(payload: StrategyInput):
    base_context = build_strategy_context(payload)

    framing_user_prompt = f"""
Analise os materiais estratégicos abaixo e construa o framing estratégico.

Retorne apenas JSON válido e compacto.

Materiais:
{base_context}
"""
    print("STEP 1 - Framing start")
    framing_data = call_llm_json(FRAMING_PROMPT, framing_user_prompt)

    try:
        framing = FramingOutput(**framing_data)
    except Exception as e:
        print("FRAMING VALIDATION ERROR:", e)
        print("RAW FRAMING DATA:", framing_data)
        raise e

    print("STEP 1 - Framing done")

    return {
        "framing": framing.model_dump()
    }


def generate_strategy_mapping(payload: StrategyMappingInput):
    base_context = build_strategy_context_from_mapping_input(payload)
    framing = payload.framing

    mapping_user_prompt = f"""
Construa o modelo executável da estratégia.

IMPORTANTE:
- siga exatamente o formato exigido no system prompt
- não crie campos extras como id, description, initiative_ids ou semelhantes
- use apenas os campos permitidos
- todo outcome deve ter linked_theme
- todo KPI deve ter type
- toda iniciativa deve ter name e linked_theme
- retorne apenas JSON válido e compacto

Regras adicionais obrigatórias:
- para cada outcome, crie pelo menos uma iniciativa diretamente associada
- para cada iniciativa, crie KPI leading operacional específico
- não deixe nenhum outcome sem cobertura de iniciativa
- se houver meta de NRR, CAC ou expansão, crie iniciativas específicas para isso
- não use gap estrutural como substituto de campos obrigatórios
- o campo gap só pode explicar uma lacuna estrutural real
- não use percentuais, metas ou targets dentro de gap
- deltas esperados devem aparecer apenas em expected_kpi_delta
- se houver expansão para México, separe o outcome local de México do outcome corporativo de ARR total
- para NRR, prefira ownership funcional coerente com retenção + expansão
- seja específico e quantitativo

Framing estratégico:
{json.dumps(framing, ensure_ascii=False)}

Materiais originais:
{base_context}
"""
    print("STEP 2 - Mapping start")
    mapping_data = call_llm_json(MAPPING_PROMPT, mapping_user_prompt)

    try:
        mapping = MappingOutput(**mapping_data)
    except Exception as e:
        print("MAPPING VALIDATION ERROR:", e)
        print("RAW MAPPING DATA:", mapping_data)
        raise e

    print("STEP 2 - Mapping done")

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
    print("STEP 3 - KPI Integrity start")
    kpi_data = call_llm_json(KPI_PROMPT, kpi_user_prompt)

    try:
        kpi_integrity = KPIIntegrityOutput(**kpi_data)
    except Exception as e:
        print("KPI VALIDATION ERROR:", e)
        print("RAW KPI DATA:", kpi_data)
        raise e

    print("STEP 3 - KPI Integrity done")

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
    print("STEP 4 - Portfolio start")
    portfolio_data = call_llm_json(PORTFOLIO_PROMPT, portfolio_user_prompt)

    try:
        portfolio = PortfolioOutput(**portfolio_data)
    except Exception as e:
        print("PORTFOLIO VALIDATION ERROR:", e)
        print("RAW PORTFOLIO DATA:", portfolio_data)
        raise e

    print("STEP 4 - Portfolio done")

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
    print("STEP 5 - Narrative start")
    narrative_data = call_llm_json(NARRATIVE_PROMPT, narrative_user_prompt)

    try:
        narrative = NarrativeOutput(**narrative_data)
    except Exception as e:
        print("NARRATIVE VALIDATION ERROR:", e)
        print("RAW NARRATIVE DATA:", narrative_data)
        raise e

    print("STEP 5 - Narrative done")

    review_result = {
        "kpi_integrity": kpi_integrity.model_dump(),
        "portfolio": portfolio.model_dump(),
        "narrative": narrative.model_dump()
    }

    print("STEP 6 - Scoring start")
    score = calculate_strategy_score(
        core_result={
            "framing": framing,
            "mapping": mapping
        },
        review_result=review_result
    )
    print("STEP 6 - Scoring done")

    review_result["strategy_score"] = score

    return review_result