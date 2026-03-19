from typing import Annotated, Optional

from fastapi import FastAPI, File, UploadFile, HTTPException

from app.models.schemas import (
    StrategyInput,
    StrategyMappingInput,
    StrategyReviewInput,
    StrategyFileIngestResponse,
    FullStrategyAnalysisResponse,
)
from app.services.orchestrator import (
    generate_strategy_framing,
    generate_strategy_mapping,
    generate_strategy_review,
    run_full_strategy_analysis,
)
from app.services.parser import extract_text_from_upload

app = FastAPI(
    title="AI Strategy OS API",
    version="0.1.0",
)


@app.get("/")
def root():
    return {"message": "AI Strategy OS API is running"}


@app.get("/health")
def health():
    return {"status": "ok"}


# =========================================================
# FILE INGESTION
# =========================================================
@app.post("/ingest-strategy-files", response_model=StrategyFileIngestResponse)
async def ingest_strategy_files_route(
    annual_plan_files: Annotated[Optional[list[UploadFile]], File()] = None,
    financial_model_files: Annotated[Optional[list[UploadFile]], File()] = None,
    market_analysis_files: Annotated[Optional[list[UploadFile]], File()] = None,
    leadership_notes_files: Annotated[Optional[list[UploadFile]], File()] = None,
    kpi_targets_files: Annotated[Optional[list[UploadFile]], File()] = None,
    scenario_assumptions_files: Annotated[Optional[list[UploadFile]], File()] = None,
    industry_reports_files: Annotated[Optional[list[UploadFile]], File()] = None,
    competitor_landscape_files: Annotated[Optional[list[UploadFile]], File()] = None,
    market_benchmarks_files: Annotated[Optional[list[UploadFile]], File()] = None,
    customer_research_files: Annotated[Optional[list[UploadFile]], File()] = None,
):
    async def join_file_text(files: Optional[list[UploadFile]], label: str) -> str:
        if not files:
            return ""

        chunks = []
        for uploaded in files:
            try:
                text = await extract_text_from_upload(uploaded)
                chunks.append(f"[{label}]\n[FILE: {uploaded.filename}]\n{text}")
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Erro ao processar arquivo {uploaded.filename}: {str(e)}")
        return "\n\n".join(chunks)

    return StrategyFileIngestResponse(
        annual_plan_text=await join_file_text(annual_plan_files, "ANNUAL PLAN"),
        financial_model_text=await join_file_text(financial_model_files, "FINANCIAL MODEL"),
        market_analysis_text=await join_file_text(market_analysis_files, "MARKET ANALYSIS"),
        leadership_notes_text=await join_file_text(leadership_notes_files, "LEADERSHIP NOTES"),
        kpi_targets_text=await join_file_text(kpi_targets_files, "KPI TARGETS"),
        scenario_assumptions_text=await join_file_text(scenario_assumptions_files, "SCENARIO ASSUMPTIONS"),
        industry_reports_text=await join_file_text(industry_reports_files, "INDUSTRY REPORTS"),
        competitor_landscape_text=await join_file_text(competitor_landscape_files, "COMPETITOR LANDSCAPE"),
        market_benchmarks_text=await join_file_text(market_benchmarks_files, "MARKET BENCHMARKS"),
        customer_research_text=await join_file_text(customer_research_files, "CUSTOMER RESEARCH"),
    )


# =========================================================
# INDIVIDUAL PIPELINE ENDPOINTS
# =========================================================
@app.post("/generate-strategy-framing")
def strategy_framing(payload: StrategyInput):
    try:
        return generate_strategy_framing(payload)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/generate-strategy-mapping")
def strategy_mapping(payload: StrategyMappingInput):
    try:
        return generate_strategy_mapping(payload)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/generate-strategy-review")
def strategy_review(payload: StrategyReviewInput):
    try:
        return generate_strategy_review(payload)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =========================================================
# CONSOLIDATED ENDPOINT
# =========================================================
@app.post("/run-strategy-analysis", response_model=FullStrategyAnalysisResponse)
def run_strategy_analysis(payload: StrategyInput):
    try:
        return run_full_strategy_analysis(payload)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))