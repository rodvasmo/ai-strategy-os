import os
import json
import re
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, ValidationError
from openai import OpenAI

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# =========================
# MODELS
# =========================

class Initiative(BaseModel):
    title: str
    description: str
    type: str


class Theme(BaseModel):
    id: int
    title: str
    description: str
    outcomes: List[str] = Field(..., min_items=3, max_items=3)
    initiatives: List[Initiative] = Field(..., min_items=5, max_items=8)


class StrategyResponse(BaseModel):
    themes: List[Theme] = Field(..., min_items=3, max_items=5)


class StrategyRequest(BaseModel):
    company_name: Optional[str] = None
    sector: Optional[str] = None
    context: Optional[str] = None
    ambition: Optional[str] = None
    objective: Optional[str] = None
    constraints: Optional[str] = ""
    language: Optional[str] = "pt-BR"


# =========================
# PROMPTS
# =========================

def system_prompt(language: str):
    return f"""
Você é um estrategista sênior.

REGRAS NÃO NEGOCIÁVEIS:

1. Gere entre 3 e 5 temas estratégicos
2. Ordene os temas do MAIS relevante para o MENOS relevante
3. Cada tema deve ter exatamente 3 outcomes
4. Cada tema deve ter ENTRE 5 E 8 iniciativas
5. NENHUM tema pode ficar sem iniciativas
6. Iniciativas devem ser:
   - específicas
   - acionáveis
   - variadas (produto, comercial, operação, tecnologia)

7. NÃO use outros nomes como actions, projects ou recommendations
8. Use APENAS "initiatives"

9. Retorne SOMENTE JSON válido

Idioma: {language}

Formato obrigatório:

{{
  "themes": [
    {{
      "id": 1,
      "title": "string",
      "description": "string",
      "outcomes": ["...", "...", "..."],
      "initiatives": [
        {{
          "title": "...",
          "description": "...",
          "type": "growth"
        }}
      ]
    }}
  ]
}}
""".strip()


def user_prompt(req: StrategyRequest):
    company_name = req.company_name or "Empresa não informada"
    sector = req.sector or "Setor não informado"
    context = req.context or "Contexto não informado"
    ambition = req.ambition or req.objective or "Ambição não informada"
    constraints = req.constraints or "Sem restrições adicionais"

    return f"""
Empresa: {company_name}
Setor: {sector}
Contexto: {context}
Ambição: {ambition}
Restrições: {constraints}

Gere a estratégia completa.
""".strip()


# =========================
# HELPERS
# =========================

def extract_json(text: str):
    try:
        return json.loads(text)
    except Exception:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise ValueError("JSON inválido")


def fix_payload(payload: dict):
    """
    Corrige erros comuns do LLM
    """
    themes = payload.get("themes", [])

    for i, t in enumerate(themes):
        t["id"] = t.get("id") or (i + 1)

        if len(t.get("outcomes", [])) < 3:
            t["outcomes"] = (t.get("outcomes", []) + ["placeholder"] * 3)[:3]

        initiatives = (
            t.get("initiatives")
            or t.get("actions")
            or t.get("projects")
            or []
        )

        fixed = []

        for item in initiatives:
            if isinstance(item, str):
                fixed.append({
                    "title": item,
                    "description": item,
                    "type": "product"
                })
            else:
                fixed.append({
                    "title": item.get("title", "Iniciativa"),
                    "description": item.get("description", "Descrição"),
                    "type": item.get("type", "product")
                })

        t["initiatives"] = fixed[:8]

    return payload


def needs_regeneration(payload: dict):
    themes = payload.get("themes", [])

    if len(themes) < 3:
        return True

    for t in themes:
        if len(t.get("initiatives", [])) < 5:
            return True

    return False


# =========================
# ENDPOINT
# =========================

@app.get("/")
def health():
    return {"status": "ok"}


@app.post("/generate-strategy-framing", response_model=StrategyResponse)
def generate_strategy(req: StrategyRequest):
    try:
        response = client.chat.completions.create(
            model="gpt-4.1",
            temperature=0.2,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt(req.language or "pt-BR")},
                {"role": "user", "content": user_prompt(req)}
            ]
        )

        content = response.choices[0].message.content
        payload = extract_json(content)
        payload = fix_payload(payload)

        if needs_regeneration(payload):
            retry = client.chat.completions.create(
                model="gpt-4.1",
                temperature=0.2,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_prompt(req.language or "pt-BR")},
                    {
                        "role": "user",
                        "content": user_prompt(req) + "\n\nRefaça garantindo que TODOS os temas tenham no mínimo 5 iniciativas."
                    }
                ]
            )

            payload = extract_json(retry.choices[0].message.content)
            payload = fix_payload(payload)

        return payload

    except ValidationError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))