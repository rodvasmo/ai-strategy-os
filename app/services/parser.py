from app.models.schemas import StrategyInput


def build_strategy_context(payload: StrategyInput) -> str:
    sections = [
        f"Company Name:\n{payload.company_name or 'Unknown'}",
        f"Company Context:\n{payload.company_context or ''}",
        f"Annual Plan:\n{payload.annual_plan_text or ''}",
        f"Financial Model:\n{payload.financial_model_text or ''}",
        f"Market Analysis:\n{payload.market_analysis_text or ''}",
        f"Leadership Notes:\n{payload.leadership_notes_text or ''}",
        f"KPI Targets:\n{payload.kpi_targets_text or ''}",
        f"Scenario Assumptions:\n{payload.scenario_assumptions_text or ''}",
    ]
    return "\n\n".join(sections)