from __future__ import annotations

import math
from typing import Any


def _safe_lower(value: Any) -> str:
    return str(value or "").strip().lower()


def _score_time_to_impact(time_horizon: str) -> int:
    text = _safe_lower(time_horizon)

    if "3" in text:
        return 100
    if "6" in text:
        return 85
    if "9" in text:
        return 65
    if "12" in text:
        return 45

    return 55


def _score_status(status: str) -> int:
    text = _safe_lower(status)

    if text == "em execução":
        return 100
    if text == "planejado":
        return 70
    if text == "concluído":
        return 40

    return 60


def _score_expected_impact(expected_impact: str, expected_kpi_delta: str, linked_theme: str) -> int:
    text = f"{expected_impact} {expected_kpi_delta} {linked_theme}".lower()

    strong_keywords = [
        "receita",
        "margem",
        "ebitda",
        "churn",
        "retenção",
        "capital de giro",
        "estoque",
        "conversão",
        "cac",
        "ltv",
        "rentabilidade",
        "ticket médio",
        "ticket",
    ]
    medium_keywords = [
        "engajamento",
        "experiência",
        "adoção",
        "produtividade",
        "eficiência",
        "automação",
        "personalização",
        "fidelização",
    ]

    strong_hits = sum(1 for k in strong_keywords if k in text)
    medium_hits = sum(1 for k in medium_keywords if k in text)

    raw_score = 35 + strong_hits * 18 + medium_hits * 9
    return max(30, min(raw_score, 100))


def _score_effort(owner: str, time_horizon: str, initiative_name: str) -> int:
    """
    Score maior = esforço menor.
    """
    owner_text = _safe_lower(owner)
    horizon_text = _safe_lower(time_horizon)
    name_text = _safe_lower(initiative_name)

    score = 65

    if "12" in horizon_text:
        score -= 20
    elif "9" in horizon_text:
        score -= 10
    elif "6" in horizon_text:
        score += 0
    elif "3" in horizon_text:
        score += 15

    complex_keywords = [
        "crm",
        "app",
        "plataforma",
        "integra",
        "dados",
        "automação",
        "jornada operacional",
        "produto",
        "arquitetura",
        "infra",
    ]
    simple_keywords = [
        "campanha",
        "pricing",
        "fidelização",
        "portfólio",
        "mix",
        "fornecedor",
        "curadoria",
        "planejamento",
    ]

    if any(k in name_text for k in complex_keywords):
        score -= 20

    if any(k in name_text for k in simple_keywords):
        score += 12

    if "ti" in owner_text or "produto" in owner_text or "tecnologia" in owner_text:
        score -= 8

    return max(20, min(score, 100))


def _infer_kpi_impacts(expected_impact: str, expected_kpi_delta: str, linked_theme: str) -> list[str]:
    text = f"{expected_impact} {expected_kpi_delta} {linked_theme}".lower()

    kpis = []

    if any(k in text for k in ["receita", "recorrente", "assinante", "conversão", "ticket"]):
        kpis.append("Receita")
    if any(k in text for k in ["ebitda", "margem", "rentabilidade"]):
        kpis.append("EBITDA")
    if any(k in text for k in ["churn", "retenção", "fidelização"]):
        kpis.append("Churn")
    if any(k in text for k in ["cac", "aquisição"]):
        kpis.append("CAC")
    if any(k in text for k in ["estoque", "capital de giro", "mix"]):
        kpis.append("Capital de Giro")
    if any(k in text for k in ["engajamento", "experiência", "nps"]):
        kpis.append("Engajamento")

    if not kpis:
        kpis.append("Execução")

    return list(dict.fromkeys(kpis))


def _infer_financial_impact_band(expected_impact: str, expected_kpi_delta: str, linked_theme: str) -> str:
    text = f"{expected_impact} {expected_kpi_delta} {linked_theme}".lower()

    if any(k in text for k in ["ebitda", "margem", "capital de giro", "estoque", "receita recorrente", "receita", "rentabilidade"]):
        return "alto"
    if any(k in text for k in ["retenção", "conversão", "cac", "produtividade", "engajamento"]):
        return "médio"
    return "baixo"


def _assign_priority_bands(enriched: list[dict]) -> list[dict]:
    """
    Classificação relativa:
    - top 25% => P1
    - next 35% => P2
    - restante => P3

    Garante distribuição mais útil em amostras pequenas.
    """
    total = len(enriched)

    if total == 0:
        return enriched

    p1_cutoff = max(1, math.ceil(total * 0.25))
    p2_cutoff = max(p1_cutoff + 1, math.ceil(total * 0.60))

    for idx, initiative in enumerate(enriched):
        rank = idx + 1
        initiative["priority_rank"] = rank

        if rank <= p1_cutoff:
            initiative["priority_band"] = "P1"
        elif rank <= p2_cutoff:
            initiative["priority_band"] = "P2"
        else:
            initiative["priority_band"] = "P3"

    return enriched


def prioritize_initiatives(mapping_data: dict) -> dict:
    initiatives = mapping_data.get("initiatives", []) or []

    enriched = []

    for initiative in initiatives:
        expected_impact = str(initiative.get("expected_impact", "")).strip()
        expected_kpi_delta = str(initiative.get("expected_kpi_delta", "")).strip()
        time_horizon = str(initiative.get("time_horizon", "")).strip()
        status = str(initiative.get("status", "")).strip()
        owner = str(initiative.get("owner", "")).strip()
        linked_theme = str(initiative.get("linked_theme", "")).strip()
        name = str(initiative.get("name", "")).strip()

        impact_score = _score_expected_impact(
            expected_impact=expected_impact,
            expected_kpi_delta=expected_kpi_delta,
            linked_theme=linked_theme,
        )
        effort_score = _score_effort(owner, time_horizon, name)
        time_score = _score_time_to_impact(time_horizon)
        execution_readiness_score = _score_status(status)

        priority_score = round(
            impact_score * 0.45
            + effort_score * 0.20
            + time_score * 0.20
            + execution_readiness_score * 0.15
        )

        initiative_copy = dict(initiative)
        initiative_copy["priority_score"] = priority_score
        initiative_copy["impact_score"] = impact_score
        initiative_copy["effort_score"] = effort_score
        initiative_copy["time_score"] = time_score
        initiative_copy["execution_readiness_score"] = execution_readiness_score
        initiative_copy["kpi_impacts"] = _infer_kpi_impacts(
            expected_impact=expected_impact,
            expected_kpi_delta=expected_kpi_delta,
            linked_theme=linked_theme,
        )
        initiative_copy["financial_impact_band"] = _infer_financial_impact_band(
            expected_impact=expected_impact,
            expected_kpi_delta=expected_kpi_delta,
            linked_theme=linked_theme,
        )

        enriched.append(initiative_copy)

    enriched.sort(key=lambda x: x["priority_score"], reverse=True)
    enriched = _assign_priority_bands(enriched)

    mapping_data["initiatives"] = enriched
    return mapping_data