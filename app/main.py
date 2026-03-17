from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.models.schemas import StrategyInput
from app.services.orchestrator import generate_strategy_model

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


@app.post("/generate-strategy")
def generate_strategy(payload: StrategyInput):
    try:
        result = generate_strategy_model(payload)
        return result.model_dump()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))