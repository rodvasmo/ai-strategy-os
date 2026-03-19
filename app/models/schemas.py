from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# =========================================================
# CORE INPUTS
# =========================================================
class StrategyInput(BaseModel):
    company_name: Optional[str] = None
    company_context: str = Field(
        ...,
        description="Contexto geral da empresa e do problema estratégico"
    )
    annual_plan_text: Optional[str] = None
    financial_model_text: Optional[str] = None
    market_analysis_text: Optional[str] = None
    leadership_notes_text: Optional[str] = None
    kpi_targets_text: Optional[str] = None
    scenario_assumptions_text: Optional[str] = None
    industry_reports_text: Optional[str] = None
    competitor_landscape_text: Optional[str] = None
    market_benchmarks_text: Optional[str] = None
    customer_research_text: Optional[str] = None


class StrategyMappingInput(BaseModel):
    framing: Dict[str, Any]
    company_name: Optional[str] = None
    company_context: Optional[str] = None
    annual_plan_text: Optional[str] = None
    financial_model_text: Optional[str] = None
    market_analysis_text: Optional[str] = None
    leadership_notes_text: Optional[str] = None
    kpi_targets_text: Optional[str] = None
    scenario_assumptions_text: Optional[str] = None
    industry_reports_text: Optional[str] = None
    competitor_landscape_text: Optional[str] = None
    market_benchmarks_text: Optional[str] = None
    customer_research_text: Optional[str] = None


class StrategyReviewInput(BaseModel):
    framing: Dict[str, Any]
    mapping: Dict[str, Any]


# =========================================================
# FILE INGESTION
# =========================================================
class StrategyFileIngestResponse(BaseModel):
    annual_plan_text: str = ""
    financial_model_text: str = ""
    market_analysis_text: str = ""
    leadership_notes_text: str = ""
    kpi_targets_text: str = ""
    scenario_assumptions_text: str = ""
    industry_reports_text: str = ""
    competitor_landscape_text: str = ""
    market_benchmarks_text: str = ""
    customer_research_text: str = ""


# =========================================================
# FRAMING
# =========================================================
class StrategicTheme(BaseModel):
    name: str
    description: str
    where_to_play: str
    how_to_win: str
    economic_logic: str
    tradeoffs: List[str]
    not_doing: List[str]
    constraints: List[str]


class FramingOutput(BaseModel):
    strategic_themes: List[StrategicTheme]
    assumptions: List[str]
    contradictions: List[str]


# =========================================================
# MAPPING
# =========================================================
class Outcome(BaseModel):
    name: str
    linked_theme: str
    target: str


class KPI(BaseModel):
    name: str
    type: str
    target: str
    owner: str
    formula: str
    source: str


class Initiative(BaseModel):
    name: str
    linked_theme: str
    linked_outcome: str
    expected_impact: str
    expected_kpi_delta: str
    time_horizon: str
    owner: str
    status: str


class StrategyGraphNode(BaseModel):
    kpi_leading: str
    kpi_lagging: str
    outcome: str
    causal_logic: str = ""


class MappingOutput(BaseModel):
    outcomes: List[Outcome]
    kpis: List[KPI]
    initiatives: List[Initiative]
    strategy_graph: Dict[str, StrategyGraphNode]


# =========================================================
# REVIEW
# =========================================================
class KPIIssue(BaseModel):
    kpi_name: str
    issue_type: str
    description: str
    recommendation: str


class KPIStandard(BaseModel):
    kpi_name: str
    suggested_formula: str
    suggested_owner: str
    suggested_source: str


class KPIIntegrityOutput(BaseModel):
    issues: List[KPIIssue]
    suggested_standards: List[KPIStandard]


class PortfolioInsight(BaseModel):
    initiative_name: str
    classification: str
    reason: str
    recommendation: str
    capital_action: str


class PortfolioOutput(BaseModel):
    insights: List[PortfolioInsight]
    overinvestment_areas: List[str]
    underinvestment_areas: List[str]


class NarrativeRecommendation(BaseModel):
    action: str
    tradeoff: str
    expected_impact: str


class NarrativeOutput(BaseModel):
    executive_summary: str
    what_is_happening: List[str]
    why_it_is_happening: List[str]
    key_risks: List[str]
    recommendations: List[NarrativeRecommendation]
    decisions_required: List[str]


# =========================================================
# SCORE
# =========================================================
class StrategyScoreDiagnostics(BaseModel):
    uncovered_outcomes: List[str]
    graph_gap_count: int
    kpi_issue_count: int
    weak_capital_actions: int


class StrategyScore(BaseModel):
    overall_score: float
    score_breakdown: Dict[str, float]
    diagnostics: StrategyScoreDiagnostics


# =========================================================
# CONSOLIDATED EXECUTIVE SUMMARY
# =========================================================
class ExecutiveSummary(BaseModel):
    headline: str
    top_insights: List[str]
    priority_actions: List[str]
    key_metrics: List[str]
    final_takeaway: str


class FullStrategyAnalysisResponse(BaseModel):
    framing: Dict[str, Any]
    mapping: Dict[str, Any]
    kpi_integrity: Dict[str, Any]
    portfolio: Dict[str, Any]
    narrative: Dict[str, Any]
    strategy_score: Dict[str, Any]
    executive_summary: ExecutiveSummary