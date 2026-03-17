import json

from app.models.schemas import (
    StrategyInput,
    StrategyResponse,
    FramingOutput,
    MappingOutput,
    KPIIntegrityOutput,
    PortfolioOutput,
    NarrativeOutput,
)
from app.services.parser import build_strategy_context
from app.services.llm import call_llm_json

from app.agents.strategy_framing_agent import SYSTEM_PROMPT as FRAMING_PROMPT
from app.agents.strategy_mapping_agent import SYSTEM_PROMPT as MAPPING_PROMPT
from app.agents.kpi_integrity_agent import SYSTEM_PROMPT as KPI_PROMPT
from app.agents.portfolio_intelligence_agent import SYSTEM_PROMPT as PORTFOLIO_PROMPT
from app.agents.narrative_agent import SYSTEM_PROMPT as NARRATIVE_PROMPT


def generate_strategy_model(payload: StrategyInput) -> StrategyResponse:
    base_context = build_strategy_context(payload)

    framing_user_prompt = f"""
Analyze the following strategy materials and build the strategic framing.

Source materials:
{base_context}
"""
    framing_data = call_llm_json(FRAMING_PROMPT, framing_user_prompt)
    framing = FramingOutput(**framing_data)

    mapping_user_prompt = f"""
Build the execution-ready strategy model based on the strategic framing and source materials.

Strategic framing:
{json.dumps(framing.model_dump(), ensure_ascii=False, indent=2)}

Source materials:
{base_context}
"""
    mapping_data = call_llm_json(MAPPING_PROMPT, mapping_user_prompt)
    mapping = MappingOutput(**mapping_data)

    kpi_user_prompt = f"""
Review the KPI layer for rigor and governance.

Mapping output:
{json.dumps(mapping.model_dump(), ensure_ascii=False, indent=2)}
"""
    kpi_data = call_llm_json(KPI_PROMPT, kpi_user_prompt)
    kpi_integrity = KPIIntegrityOutput(**kpi_data)

    portfolio_user_prompt = f"""
Review the initiative portfolio against strategy and KPI impact.

Framing:
{json.dumps(framing.model_dump(), ensure_ascii=False, indent=2)}

Mapping:
{json.dumps(mapping.model_dump(), ensure_ascii=False, indent=2)}

KPI Integrity:
{json.dumps(kpi_integrity.model_dump(), ensure_ascii=False, indent=2)}
"""
    portfolio_data = call_llm_json(PORTFOLIO_PROMPT, portfolio_user_prompt)
    portfolio = PortfolioOutput(**portfolio_data)

    narrative_user_prompt = f"""
Write the executive strategy narrative.

Framing:
{json.dumps(framing.model_dump(), ensure_ascii=False, indent=2)}

Mapping:
{json.dumps(mapping.model_dump(), ensure_ascii=False, indent=2)}

KPI Integrity:
{json.dumps(kpi_integrity.model_dump(), ensure_ascii=False, indent=2)}

Portfolio:
{json.dumps(portfolio.model_dump(), ensure_ascii=False, indent=2)}
"""
    narrative_data = call_llm_json(NARRATIVE_PROMPT, narrative_user_prompt)
    narrative = NarrativeOutput(**narrative_data)

    return StrategyResponse(
        framing=framing,
        mapping=mapping,
        kpi_integrity=kpi_integrity,
        portfolio=portfolio,
        narrative=narrative,
    )