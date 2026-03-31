from typing import Any, Dict, List, Optional, Literal

from pydantic import BaseModel, Field


# =========================================================
# GUARDRAILS
# =========================================================
GuardrailCategory = Literal[
    "financeiro",
    "comercial",
    "cliente",
    "pessoas",
    "operacional",
    "governanca",
]

GuardrailOperator = Literal[
    ">=",
    "<=",
    "==",
    "between",
    "text_rule",
]

GuardrailPriority = Literal[
    "critico",
    "alto",
    "medio",
]

GuardrailStatus = Literal[
    "ativo",
    "inativo",
]


class Guardrail(BaseModel):
    id: Optional[str] = None
    name: str
    category: GuardrailCategory
    description: str
    metric_name: Optional[str] = None
    operator: GuardrailOperator = "text_rule"
    target_value: Optional[str] = None
    target_unit: Optional[str] = None
    priority: GuardrailPriority = "medio"
    owner: Optional[str] = None
    scope: str = "empresa"
    source: str = "manual"
    rationale: Optional[str] = None
    status: GuardrailStatus = "ativo"


# =========================================================
# CORE INPUTS
# =========================================================
class StrategyInput(BaseModel):
    company_name: Optional[str] = None
    company_context: str = Field(
        ...,
        description="Contexto geral da empresa e do problema estratégico",
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
    performance_constraints_text: Optional[str] = None
    performance_constraints: List[Guardrail] = Field(default_factory=list)


class StrategyOutcomesKPIsInput(BaseModel):
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
    performance_constraints_text: Optional[str] = None
    performance_constraints: List[Guardrail] = Field(default_factory=list)


class StrategyInitiativesInput(BaseModel):
    framing: Dict[str, Any]
    outcomes: List[Dict[str, Any]]
    kpis: List[Dict[str, Any]]
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
    performance_constraints_text: Optional[str] = None
    performance_constraints: List[Guardrail] = Field(default_factory=list)


class StrategyReviewInput(BaseModel):
    framing: Dict[str, Any]
    outcomes: List[Dict[str, Any]]
    kpis: List[Dict[str, Any]]
    initiatives: List[Dict[str, Any]]
    strategy_graph: Dict[str, Any]
    performance_constraints: List[Guardrail] = Field(default_factory=list)


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
# OUTCOMES + KPI HIERARCHY
# =========================================================
KPIType = Literal["leading", "lagging"]
KPILevel = Literal["north_star", "driver", "supporting"]


class Outcome(BaseModel):
    name: str
    linked_theme: str
    target: str
    timeframe: str
    value_driver: str


class KPI(BaseModel):
    name: str
    type: KPIType
    level: KPILevel
    linked_outcomes: List[str]
    parent_kpi: Optional[str] = None
    target: str
    owner: str
    formula: str
    source: str

    quality_flags: Optional[List[str]] = None
    quality_score: Optional[int] = None


class OutcomesKPIsOutput(BaseModel):
    outcomes: List[Outcome]
    kpis: List[KPI]


# =========================================================
# INITIATIVES
# =========================================================
class Initiative(BaseModel):
    name: str
    linked_theme: str
    linked_outcome: str
    linked_kpis: List[str]
    expected_impact: str
    expected_kpi_delta: str
    time_horizon: str
    owner: str
    status: str

    priority_score: Optional[int] = None
    priority_band: Optional[str] = None
    priority_rank: Optional[int] = None
    impact_score: Optional[int] = None
    effort_score: Optional[int] = None
    time_score: Optional[int] = None
    execution_readiness_score: Optional[int] = None
    kpi_impacts: Optional[List[str]] = None
    financial_impact_band: Optional[str] = None


class StrategyGraphNode(BaseModel):
    kpi_leading: str
    kpi_lagging: str
    outcome: str
    causal_logic: str = ""


# =========================================================
# STRATEGY COVERAGE
# =========================================================
class KPICoverageItem(BaseModel):
    kpi_name: str
    kpi_type: str
    outcome_names: List[str]
    initiative_count: int
    initiative_names: List[str]
    covered: bool


class OutcomeCoverageItem(BaseModel):
    outcome_name: str
    total_kpis: int
    covered_kpis: int
    uncovered_kpis: List[str]
    fully_covered: bool


class StrategyCoverageOutput(BaseModel):
    total_outcomes: int
    covered_outcomes: int
    total_kpis: int
    covered_kpis: int
    uncovered_kpis_count: int
    kpi_coverage_pct: float
    outcome_coverage_pct: float
    uncovered_kpis: List[KPICoverageItem]
    kpi_coverage_details: List[KPICoverageItem]
    outcome_coverage_details: List[OutcomeCoverageItem]


class InitiativesOutput(BaseModel):
    initiatives: List[Initiative]
    strategy_graph: Dict[str, StrategyGraphNode]
    strategy_coverage: Optional[StrategyCoverageOutput] = None


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
    outcomes: List[Dict[str, Any]]
    kpis: List[Dict[str, Any]]
    initiatives: List[Dict[str, Any]]
    strategy_graph: Dict[str, Any]
    strategy_coverage: Optional[Dict[str, Any]] = None
    kpi_integrity: Dict[str, Any]
    portfolio: Dict[str, Any]
    narrative: Dict[str, Any]
    strategy_score: Dict[str, Any]
    executive_summary: ExecutiveSummary