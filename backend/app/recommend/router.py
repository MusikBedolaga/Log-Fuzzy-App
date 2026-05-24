from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel

from app.db.repository import get_log
from app.recommend import ollama_client, pg_store
from app.recommend.config import EMBED_MODEL, LLM_MODEL, OLLAMA_BASE_URL

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/recommend", tags=["recommend"])


class SimilarRequest(BaseModel):
    log_id: int
    limit: int = 5


class AdviceRequest(BaseModel):
    log_id: int


class IndexRequest(BaseModel):
    log_id: int


def _log_to_text(log: dict) -> str:
    parts = [
        log.get("level") or "",
        log.get("component") or "",
        log.get("event_type") or "",
        log.get("message") or log.get("raw_text") or "",
    ]
    return " | ".join(p for p in parts if p) or "unknown"


def index_one_log(log_id: int) -> None:
    """Генерирует эмбеддинг для лога и сохраняет в pgvector. Безопасно при ошибках."""
    try:
        log = get_log(log_id)
        if log is None:
            return
        text = _log_to_text(log)
        embedding = ollama_client.get_embedding(text)
        pg_store.upsert_embedding(
            log_id,
            embedding,
            source_name=log.get("source_name") or "",
            level=log.get("level") or "",
            component=log.get("component") or "",
            event_type=log.get("event_type") or "",
            criticality=float(log.get("criticality") or 0),
            message=log.get("message") or log.get("raw_text") or "",
        )
        logger.debug("Indexed log_id=%d", log_id)
    except Exception as exc:
        logger.warning("index_one_log log_id=%s failed: %s", log_id, exc)


def _bulk_index(limit: int, min_criticality: float) -> None:
    from app.db.connection import get_connection

    try:
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT id FROM logs WHERE criticality >= ? ORDER BY criticality DESC LIMIT ?",
                (min_criticality, limit),
            ).fetchall()
        total = len(rows)
        logger.info("Bulk index started: %d logs (limit=%d, min_crit=%.2f)", total, limit, min_criticality)
        for i, row in enumerate(rows):
            index_one_log(row["id"])
            if (i + 1) % 50 == 0:
                logger.info("Bulk index progress: %d / %d", i + 1, total)
        logger.info("Bulk index complete: %d logs", total)
    except Exception as exc:
        logger.error("Bulk index failed: %s", exc)


@router.get("/status")
def status() -> dict:
    return {
        "ollama_reachable": ollama_client.is_ollama_reachable(),
        "ollama_url": OLLAMA_BASE_URL,
        "embed_model": EMBED_MODEL,
        "llm_model": LLM_MODEL,
        "pg_indexed": pg_store.count_indexed(),
    }


@router.post("/index")
def index_one(payload: IndexRequest, background_tasks: BackgroundTasks) -> dict:
    log = get_log(payload.log_id)
    if log is None:
        raise HTTPException(status_code=404, detail="Лог не найден")
    background_tasks.add_task(index_one_log, payload.log_id)
    return {"status": "queued", "log_id": payload.log_id}


@router.post("/index-all")
def index_all(
    background_tasks: BackgroundTasks,
    limit: int = Query(default=500, ge=1, le=5000),
    min_criticality: float = Query(default=0.0, ge=0.0, le=1.0),
) -> dict:
    background_tasks.add_task(_bulk_index, limit, min_criticality)
    return {
        "status": "started",
        "limit": limit,
        "min_criticality": min_criticality,
        "message": f"Индексация запущена в фоне (до {limit} логов, criticality ≥ {min_criticality})",
    }


@router.post("/similar")
def find_similar(payload: SimilarRequest) -> dict:
    log = get_log(payload.log_id)
    if log is None:
        raise HTTPException(status_code=404, detail="Лог не найден")
    try:
        embedding = ollama_client.get_embedding(_log_to_text(log))
        similar = pg_store.find_similar(
            embedding, exclude_id=payload.log_id, limit=max(1, min(payload.limit, 20))
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"log_id": payload.log_id, "similar": similar}


@router.post("/advice")
def get_advice(payload: AdviceRequest) -> dict:
    log = get_log(payload.log_id)
    if log is None:
        raise HTTPException(status_code=404, detail="Лог не найден")
    try:
        embedding = ollama_client.get_embedding(_log_to_text(log))
        similar = pg_store.find_similar(embedding, exclude_id=payload.log_id, limit=3)
        advice = ollama_client.get_advice(log, similar)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"log_id": payload.log_id, "advice": advice, "similar": similar}
