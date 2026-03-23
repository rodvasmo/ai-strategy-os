from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import json

# ---------------------------------------------------
# APP INIT
# ---------------------------------------------------

app = FastAPI()

# ---------------------------------------------------
# CORS (FIX DEFINITIVO DO 405)
# ---------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # depois pode restringir
    allow_credentials=True,
    allow_methods=["*"],  # 🔥 ESSENCIAL PARA OPTIONS
    allow_headers=["*"],
)

# ---------------------------------------------------
# MODELS
# ---------------------------------------------------

class StrategyInput(BaseModel):
    context: str
    objective: str

# ---------------------------------------------------
# HEALTH CHECK
# ---------------------------------------------------

@app.get("/")
def health():
    return {"status": "ok"}

# ---------------------------------------------------
# MOCK LLM CALL (SUBSTITUA PELO SEU CLIENT)
# ---------------------------------------------------

def call_llm(prompt: str):
    # ⚠️ Substitua isso pela sua integração real com OpenAI
    return {
        "themes": [],
        "outcomes": [],
        "initiatives": []
    }

# ---------------------------------------------------
# VALIDATION
# ---------------------------------------------------

def validate_response(data: dict):
    if "outcomes" not in data or len(data["outcomes"]) == 0:
        raise ValueError("No outcomes generated")

    if "initiatives" not in data or len(data["initiatives"]) == 0:
        raise ValueError("No initiatives generated")

    return data

# ---------------------------------------------------
# ENDPOINT 1 — FRAMING
# ---------------------------------------------------

@app.post("/generate-strategy-framing")
def generate_framing(input: StrategyInput):
    try:
        prompt = f"""
        Generate strategic themes (3 to 5), outcomes and initiatives.
        Context: {input.context}
        Objective: {input.objective}
        """

        response = call_llm(prompt)

        validated = validate_response(response)

        return validated

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------------------------------
# ENDPOINT 2 — MAPPING
# ---------------------------------------------------

@app.post("/generate-strategy-mapping")
def generate_mapping(input: StrategyInput):
    try:
        prompt = f"""
        Generate KPIs and initiatives based on strategy.
        Context: {input.context}
        Objective: {input.objective}
        """

        response = call_llm(prompt)

        # aqui você pode validar diferente se quiser
        return response

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))