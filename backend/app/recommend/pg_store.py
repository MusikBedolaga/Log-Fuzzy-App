from __future__ import annotations

import logging
from typing import Any

import numpy as np
import psycopg2
import psycopg2.extras
from pgvector.psycopg2 import register_vector

from app.recommend.config import EMBED_DIM, POSTGRES_DSN

logger = logging.getLogger(__name__)


def _connect() -> psycopg2.extensions.connection:
    conn = psycopg2.connect(POSTGRES_DSN)
    conn.autocommit = False
    register_vector(conn)
    return conn


def init_pg() -> None:
    try:
        conn = _connect()
        try:
            with conn.cursor() as cur:
                cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
                cur.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS log_embeddings (
                        log_id      INTEGER PRIMARY KEY,
                        source_name TEXT    NOT NULL DEFAULT '',
                        level       TEXT    NOT NULL DEFAULT '',
                        component   TEXT    NOT NULL DEFAULT '',
                        event_type  TEXT    NOT NULL DEFAULT '',
                        criticality REAL    NOT NULL DEFAULT 0,
                        message     TEXT    NOT NULL DEFAULT '',
                        embedding   vector({EMBED_DIM}) NOT NULL
                    )
                    """
                )
            conn.commit()
        finally:
            conn.close()
        logger.info("pgvector store initialized (dim=%d)", EMBED_DIM)
    except Exception as exc:
        logger.warning(
            "pgvector init skipped — recommend features will be unavailable: %s", exc
        )


def upsert_embedding(
    log_id: int,
    embedding: list[float],
    *,
    source_name: str = "",
    level: str = "",
    component: str = "",
    event_type: str = "",
    criticality: float = 0.0,
    message: str = "",
) -> None:
    vec = np.array(embedding, dtype=np.float32)
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO log_embeddings
                    (log_id, source_name, level, component, event_type, criticality, message, embedding)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (log_id) DO UPDATE SET
                    source_name = EXCLUDED.source_name,
                    level       = EXCLUDED.level,
                    component   = EXCLUDED.component,
                    event_type  = EXCLUDED.event_type,
                    criticality = EXCLUDED.criticality,
                    message     = EXCLUDED.message,
                    embedding   = EXCLUDED.embedding
                """,
                (
                    log_id,
                    source_name,
                    level,
                    component,
                    event_type,
                    float(criticality),
                    message,
                    vec,
                ),
            )
        conn.commit()
    finally:
        conn.close()


def find_similar(
    embedding: list[float],
    *,
    exclude_id: int | None = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    vec = np.array(embedding, dtype=np.float32)
    conn = _connect()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if exclude_id is not None:
                cur.execute(
                    """
                    SELECT
                        log_id, source_name, level, component, event_type, criticality, message,
                        (1 - (embedding <=> %s)) AS similarity
                    FROM log_embeddings
                    WHERE log_id <> %s
                    ORDER BY embedding <=> %s
                    LIMIT %s
                    """,
                    (vec, exclude_id, vec, limit),
                )
            else:
                cur.execute(
                    """
                    SELECT
                        log_id, source_name, level, component, event_type, criticality, message,
                        (1 - (embedding <=> %s)) AS similarity
                    FROM log_embeddings
                    ORDER BY embedding <=> %s
                    LIMIT %s
                    """,
                    (vec, vec, limit),
                )
            rows = cur.fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["similarity"] = round(float(d.get("similarity") or 0), 4)
            d["criticality"] = round(float(d.get("criticality") or 0), 4)
            result.append(d)
        return result
    finally:
        conn.close()


def delete_embedding(log_id: int) -> None:
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM log_embeddings WHERE log_id = %s", (log_id,))
        conn.commit()
    finally:
        conn.close()


def count_indexed() -> int:
    try:
        conn = _connect()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM log_embeddings")
                return int(cur.fetchone()[0])
        finally:
            conn.close()
    except Exception:
        return -1
