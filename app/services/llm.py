import json
import re
from openai import OpenAI
from app.config import OPENAI_API_KEY, OPENAI_MODEL

client = OpenAI(api_key=OPENAI_API_KEY)


def extract_json_object(text: str) -> str:
    text = text.strip()

    if text.startswith("```json"):
        text = text.replace("```json", "", 1).strip()
    if text.startswith("```"):
        text = text.replace("```", "", 1).strip()
    if text.endswith("```"):
        text = text[:-3].strip()

    # tenta pegar só o bloco entre o primeiro { e o último }
    start = text.find("{")
    end = text.rfind("}")

    if start != -1 and end != -1 and end > start:
        return text[start:end + 1].strip()

    return text


def call_llm_json(system_prompt: str, user_prompt: str) -> dict:
    response = client.responses.create(
        model=OPENAI_MODEL,
        input=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        max_output_tokens=1800,
    )

    text = response.output_text.strip()
    cleaned = extract_json_object(text)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        print("RAW LLM RESPONSE:\n", text)
        print("\nCLEANED RESPONSE:\n", cleaned)
        raise ValueError(f"JSON inválido retornado pelo modelo: {str(e)}")