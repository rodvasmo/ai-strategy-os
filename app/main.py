from typing import Annotated, Optional

from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.models.schemas import (
    StrategyInput,
    StrategyOutcomesKPIsInput,
    StrategyInitiativesInput,
    StrategyReviewInput,
    StrategyFileIngestResponse,
    FullStrategyAnalysisResponse,
)

from app.services.orchestrator import (
    generate_strategy_framing,
    generate_strategy_outcomes_kpis,
    generate_strategy_initiatives,
    generate_strategy_review,
    run_full_strategy_analysis,
)

from app.services.parser import extract_text_from_upload


app = FastAPI(
    title="AI Strategy OS API",
    version="0.2.0",
)

# =========================================================
# CORS
# =========================================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # depois restringe
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
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
                raise HTTPException(
                    status_code=400,
                    detail=f"Erro ao processar arquivo {uploaded.filename}: {str(e)}",
                )

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
# NEW PIPELINE ENDPOINTS
# =========================================================

@app.post("/generate-strategy-framing")
def strategy_framing(payload: StrategyInput):
    try:
        return generate_strategy_framing(payload)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/generate-strategy-outcomes-kpis")
def strategy_outcomes_kpis(payload: StrategyOutcomesKPIsInput):
    try:
        return generate_strategy_outcomes_kpis(payload)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/generate-strategy-initiatives")
def strategy_initiatives(payload: StrategyInitiativesInput):
    try:
        return generate_strategy_initiatives(payload)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/generate-strategy-review")
def strategy_review(payload: StrategyReviewInput):
    try:
        return generate_strategy_review(payload)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =========================================================
# FULL PIPELINE (END-TO-END)
# =========================================================
@app.post("/run-strategy-analysis", response_model=FullStrategyAnalysisResponse)
def run_strategy_analysis(payload: StrategyInput):
    try:
        return run_full_strategy_analysis(payload)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =========================================================
# (OPCIONAL) LEGACY ENDPOINT PARA NÃO QUEBRAR FRONT
# =========================================================
# Se quiser manter compatibilidade com o fluxo antigo temporariamente

"""
from app.models.schemas import StrategyMappingInput

@app.post("/generate-strategy-mapping")
def legacy_mapping(payload: StrategyMappingInput):
    try:
        framing = payload.framing

        outcomes_kpis = generate_strategy_outcomes_kpis(
            StrategyOutcomesKPIsInput(
                framing=framing,
                **payload.model_dump(exclude={"framing"})
            )
        )

        initiatives = generate_strategy_initiatives(
            StrategyInitiativesInput(
                framing=framing,
                outcomes=outcomes_kpis["outcomes"],
                kpis=outcomes_kpis["kpis"],
                **payload.model_dump(exclude={"framing"})
            )
        )

        return {
            "outcomes": outcomes_kpis["outcomes"],
            "kpis": outcomes_kpis["kpis"],
            "initiatives": initiatives["initiatives"],
            "strategy_graph": initiatives["strategy_graph"],
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
"""