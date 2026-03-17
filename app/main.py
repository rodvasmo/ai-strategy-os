from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.models.schemas import (
    StrategyInput,
    StrategyMappingInput,
    StrategyReviewInput,
)
from app.services.orchestrator import (
    generate_strategy_framing,
    generate_strategy_mapping,
    generate_strategy_review,
)

app = FastAPI(title="AI Strategy OS API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return {"message": "AI Strategy OS API running"}


@app.get("/health")
def health():
    return {"status": "ok"}


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