from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class StrategyInput(BaseModel):
    company_name: Optional[str] = None
    company_context: str = Field(..., description="Context about the company and strategy situation")
    annual_plan_text: Optional[str] = None
    financial_model_text: Optional[str] = None
    market_analysis_text: Optional[str] = None
    leadership_notes_text: Optional[str] = None
    kpi_targets_text: Optional[str] = None
    scenario_assumptions_text: Optional[str] = None


class StrategyTheme(BaseModel):
    name: str
    description: str
    where_to_play: Optional[str] = None
    how_to_win: Optional[str] = None
    economic_logic: Optional[str] = None
    tradeoffs: List[str] = []
    not_doing: List[str] = []


class FramingOutput(BaseModel):
    strategic_themes: List[StrategyTheme]
    assumptions: List[str]
    contradictions: List[str]


class Outcome(BaseModel):
    name: str
    linked_theme: str
    target: Optional[str] = None


class KPI(BaseModel):
    name: str
    type: str
    target: Optional[str] = None
    owner: Optional[str] = None
    formula: Optional[str] = None
    source: Optional[str] = None


class Initiative(BaseModel):
    name: str
    linked_theme: str
    linked_outcome: Optional[str] = None
    expected_impact: Optional[str] = None
    owner: Optional[str] = None
    status: Optional[str] = None


class MappingOutput(BaseModel):
    outcomes: List[Outcome]
    kpis: List[KPI]
    initiatives: List[Initiative]
    strategy_graph: Dict[str, Any]


class KPIIssue(BaseModel):
    kpi_name: str
    issue_type: str
    description: str
    recommendation: Optional[str] = None


class KPIIntegrityOutput(BaseModel):
    issues: List[KPIIssue]
    suggested_standards: List[Dict[str, str]]


class PortfolioInsight(BaseModel):
    initiative_name: str
    classification: str
    reason: str
    recommendation: str


class PortfolioOutput(BaseModel):
    insights: List[PortfolioInsight]
    overinvestment_areas: List[str]
    underinvestment_areas: List[str]


class NarrativeOutput(BaseModel):
    executive_summary: str
    what_is_happening: List[str]
    why_it_is_happening: List[str]
    key_risks: List[str]
    recommendations: List[str]
    decisions_required: List[str]


class StrategyResponse(BaseModel):
    framing: FramingOutput
    mapping: MappingOutput
    kpi_integrity: KPIIntegrityOutput
    portfolio: PortfolioOutput
    narrative: NarrativeOutput