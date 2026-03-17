from app.models.schemas import StrategyInput, StrategyMappingInput


def build_strategy_context(payload: StrategyInput) -> str:
    sections = [
        f"Nome da empresa:\n{payload.company_name or 'Não informado'}",
        f"Contexto da empresa:\n{payload.company_context or ''}",
        f"Plano anual:\n{payload.annual_plan_text or ''}",
        f"Modelo financeiro / orçamento:\n{payload.financial_model_text or ''}",
        f"Análise de mercado:\n{payload.market_analysis_text or ''}",
        f"Notas da liderança:\n{payload.leadership_notes_text or ''}",
        f"KPIs e metas:\n{payload.kpi_targets_text or ''}",
        f"Premissas de cenário:\n{payload.scenario_assumptions_text or ''}",
    ]
    return "\n\n".join(sections)


def build_strategy_context_from_mapping_input(payload: StrategyMappingInput) -> str:
    sections = [
        f"Nome da empresa:\n{payload.company_name or 'Não informado'}",
        f"Contexto da empresa:\n{payload.company_context or ''}",
        f"Plano anual:\n{payload.annual_plan_text or ''}",
        f"Modelo financeiro / orçamento:\n{payload.financial_model_text or ''}",
        f"Análise de mercado:\n{payload.market_analysis_text or ''}",
        f"Notas da liderança:\n{payload.leadership_notes_text or ''}",
        f"KPIs e metas:\n{payload.kpi_targets_text or ''}",
        f"Premissas de cenário:\n{payload.scenario_assumptions_text or ''}",
    ]
    return "\n\n".join(sections)