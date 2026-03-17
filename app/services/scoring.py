from typing import Any, Dict


def calculate_strategy_score(core_result: Dict[str, Any], review_result: Dict[str, Any]) -> Dict[str, Any]:
    framing = core_result.get("framing", {})
    mapping = core_result.get("mapping", {})
    kpi_integrity = review_result.get("kpi_integrity", {})
    portfolio = review_result.get("portfolio", {})

    strategic_themes = framing.get("strategic_themes", [])
    assumptions = framing.get("assumptions", [])
    contradictions = framing.get("contradictions", [])

    outcomes = mapping.get("outcomes", [])
    kpis = mapping.get("kpis", [])
    initiatives = mapping.get("initiatives", [])
    strategy_graph = mapping.get("strategy_graph", {})

    kpi_issues = kpi_integrity.get("issues", [])
    portfolio_insights = portfolio.get("insights", [])
    overinvestment_areas = portfolio.get("overinvestment_areas", [])
    underinvestment_areas = portfolio.get("underinvestment_areas", [])

    # 1. Clarity Score
    clarity_score = 100

    if len(strategic_themes) == 0:
        clarity_score -= 60
    elif len(strategic_themes) > 5:
        clarity_score -= 20

    missing_how_to_win = sum(1 for t in strategic_themes if not t.get("how_to_win"))
    missing_economic_logic = sum(1 for t in strategic_themes if not t.get("economic_logic"))
    missing_tradeoffs = sum(1 for t in strategic_themes if not t.get("tradeoffs"))
    missing_not_doing = sum(1 for t in strategic_themes if not t.get("not_doing"))

    clarity_score -= missing_how_to_win * 10
    clarity_score -= missing_economic_logic * 10
    clarity_score -= missing_tradeoffs * 8
    clarity_score -= missing_not_doing * 8

    if len(assumptions) < 3:
        clarity_score -= 10

    if len(contradictions) == 0:
        clarity_score -= 10

    clarity_score = max(0, min(100, clarity_score))

    # 2. KPI Integrity Score
    kpi_integrity_score = 100

    if len(kpis) == 0:
        kpi_integrity_score = 0
    else:
        kpi_integrity_score -= min(60, len(kpi_issues) * 8)

        missing_owner_count = sum(1 for k in kpis if not k.get("owner"))
        missing_formula_count = sum(1 for k in kpis if not k.get("formula"))
        missing_source_count = sum(1 for k in kpis if not k.get("source"))

        kpi_integrity_score -= missing_owner_count * 8
        kpi_integrity_score -= missing_formula_count * 6
        kpi_integrity_score -= missing_source_count * 6

    kpi_integrity_score = max(0, min(100, kpi_integrity_score))

    # 3. Execution Coverage Score
    execution_coverage_score = 100

    if len(outcomes) == 0:
        execution_coverage_score -= 50
    if len(initiatives) == 0:
        execution_coverage_score -= 50

    outcome_names = {o.get("name") for o in outcomes}
    initiative_linked_outcomes = {i.get("linked_outcome") for i in initiatives if i.get("linked_outcome")}

    uncovered_outcomes = outcome_names - initiative_linked_outcomes
    execution_coverage_score -= min(40, len(uncovered_outcomes) * 10)

    graph_gaps = 0
    for node in strategy_graph.values():
        if node.get("gap"):
            graph_gaps += 1
        if not node.get("kpi_leading"):
            graph_gaps += 1
        if not node.get("kpi_lagging"):
            graph_gaps += 1

    execution_coverage_score -= min(40, graph_gaps * 6)
    execution_coverage_score = max(0, min(100, execution_coverage_score))

    # 4. Capital Allocation Score
    capital_allocation_score = 100

    if len(portfolio_insights) == 0:
        capital_allocation_score -= 50

    weak_capital_actions = 0
    for insight in portfolio_insights:
        if not insight.get("capital_action"):
            weak_capital_actions += 1
        elif insight.get("capital_action") == "maintain":
            weak_capital_actions += 1

    capital_allocation_score -= min(40, weak_capital_actions * 12)
    capital_allocation_score -= min(20, len(overinvestment_areas) * 8)
    capital_allocation_score -= min(20, len(underinvestment_areas) * 8)

    capital_allocation_score = max(0, min(100, capital_allocation_score))

    # Weighted final score
    overall_score = round(
        (clarity_score * 0.30)
        + (kpi_integrity_score * 0.25)
        + (execution_coverage_score * 0.25)
        + (capital_allocation_score * 0.20),
        1
    )

    return {
        "overall_score": overall_score,
        "score_breakdown": {
            "clarity": clarity_score,
            "kpi_integrity": kpi_integrity_score,
            "execution_coverage": execution_coverage_score,
            "capital_allocation": capital_allocation_score,
        },
        "diagnostics": {
            "uncovered_outcomes": list(uncovered_outcomes),
            "graph_gap_count": graph_gaps,
            "kpi_issue_count": len(kpi_issues),
            "weak_capital_actions": weak_capital_actions,
        }
    }