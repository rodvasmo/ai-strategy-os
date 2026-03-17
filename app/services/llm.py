import json
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

    start = text.find("{")
    end = text.rfind("}")

    if start != -1 and end != -1 and end > start:
        return text[start:end + 1].strip()

    return text


def repair_json_with_llm(bad_json_text: str) -> dict:
    repair_system_prompt = """
Você é um reparador de JSON.
Sua tarefa é receber um texto que deveria ser JSON, mas está com sintaxe inválida, e devolver apenas JSON válido.
Não invente conteúdo novo.
Não explique nada.
Não use markdown.
Retorne apenas o JSON corrigido.
"""

    response = client.responses.create(
        model=OPENAI_MODEL,
        input=[
            {"role": "system", "content": repair_system_prompt},
            {
                "role": "user",
                "content": f"Corrija este JSON inválido e devolva apenas JSON válido:\n\n{bad_json_text}"
            },
        ],
        max_output_tokens=2200,
    )

    repaired_text = extract_json_object(response.output_text)
    return json.loads(repaired_text)


def call_llm_json(system_prompt: str, user_prompt: str) -> dict:
    response = client.responses.create(
        model=OPENAI_MODEL,
        input=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        max_output_tokens=1800,
    )

    raw_text = response.output_text.strip()
    cleaned_text = extract_json_object(raw_text)

    try:
        return json.loads(cleaned_text)
    except json.JSONDecodeError as e:
        print("RAW LLM RESPONSE:\n", raw_text)
        print("\nCLEANED RESPONSE:\n", cleaned_text)
        print("\nJSON ERROR:\n", str(e))
        try:
            repaired = repair_json_with_llm(cleaned_text)
            print("\nJSON REPAIR SUCCESS")
            return repaired
        except Exception as repair_error:
            print("\nJSON REPAIR FAILED:\n", str(repair_error))
            raise ValueError(f"JSON inválido retornado pelo modelo: {str(e)}")