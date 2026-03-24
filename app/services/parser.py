from __future__ import annotations

import io
import json
import re
import zipfile
from typing import Any, Optional

from fastapi import UploadFile


def _clean_text(value: Optional[str]) -> str:
    return (value or "").strip()


def build_strategy_context(payload: Any) -> str:
    sections = []

    if _clean_text(getattr(payload, "company_name", None)):
        sections.append(f"[COMPANY NAME]\n{payload.company_name}")

    if _clean_text(getattr(payload, "company_context", None)):
        sections.append(f"[COMPANY CONTEXT]\n{payload.company_context}")

    if _clean_text(getattr(payload, "annual_plan_text", None)):
        sections.append(f"[ANNUAL PLAN]\n{payload.annual_plan_text}")

    if _clean_text(getattr(payload, "financial_model_text", None)):
        sections.append(f"[FINANCIAL MODEL]\n{payload.financial_model_text}")

    if _clean_text(getattr(payload, "market_analysis_text", None)):
        sections.append(f"[MARKET ANALYSIS]\n{payload.market_analysis_text}")

    if _clean_text(getattr(payload, "leadership_notes_text", None)):
        sections.append(f"[LEADERSHIP NOTES]\n{payload.leadership_notes_text}")

    if _clean_text(getattr(payload, "kpi_targets_text", None)):
        sections.append(f"[KPI TARGETS]\n{payload.kpi_targets_text}")

    if _clean_text(getattr(payload, "scenario_assumptions_text", None)):
        sections.append(f"[SCENARIO ASSUMPTIONS]\n{payload.scenario_assumptions_text}")

    if _clean_text(getattr(payload, "industry_reports_text", None)):
        sections.append(f"[INDUSTRY REPORTS]\n{payload.industry_reports_text}")

    if _clean_text(getattr(payload, "competitor_landscape_text", None)):
        sections.append(f"[COMPETITOR LANDSCAPE]\n{payload.competitor_landscape_text}")

    if _clean_text(getattr(payload, "market_benchmarks_text", None)):
        sections.append(f"[MARKET BENCHMARKS]\n{payload.market_benchmarks_text}")

    if _clean_text(getattr(payload, "customer_research_text", None)):
        sections.append(f"[CUSTOMER RESEARCH]\n{payload.customer_research_text}")

    if _clean_text(getattr(payload, "performance_constraints_text", None)):
        sections.append(f"[PERFORMANCE CONSTRAINTS]\n{payload.performance_constraints_text}")

    return "\n\n".join(sections)


def build_strategy_context_from_mapping_input(payload: Any) -> str:
    return build_strategy_context(payload)


async def extract_text_from_upload(upload: UploadFile) -> str:
    content = await upload.read()
    filename = (upload.filename or "").lower()
    content_type = (upload.content_type or "").lower()

    if (
        filename.endswith(".txt")
        or filename.endswith(".md")
        or filename.endswith(".csv")
        or filename.endswith(".json")
        or content_type.startswith("text/")
        or content_type in {"application/json", "text/csv"}
    ):
        try:
            if filename.endswith(".json") or content_type == "application/json":
                parsed = json.loads(content.decode("utf-8", errors="ignore"))
                return json.dumps(parsed, ensure_ascii=False, indent=2)
            return content.decode("utf-8", errors="ignore")
        except Exception:
            return content.decode("latin-1", errors="ignore")

    if filename.endswith(".pdf") or content_type == "application/pdf":
        try:
            from pypdf import PdfReader  # type: ignore

            reader = PdfReader(io.BytesIO(content))
            pages = []
            for page in reader.pages:
                pages.append(page.extract_text() or "")
            text = "\n".join(pages).strip()
            if text:
                return text
        except Exception:
            pass

        return content.decode("utf-8", errors="ignore")

    if filename.endswith(".docx"):
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as z:
                xml_bytes = z.read("word/document.xml")
            xml_text = xml_bytes.decode("utf-8", errors="ignore")
            cleaned = re.sub(r"<[^>]+>", " ", xml_text)
            cleaned = re.sub(r"\s+", " ", cleaned).strip()
            return cleaned
        except Exception:
            return content.decode("utf-8", errors="ignore")

    return content.decode("utf-8", errors="ignore")