from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from app.core.log_model import analyze_lines, analyze_path
from app.db.connection import get_connection

LOG_INSERT_COLUMNS = [
    "source_id",
    "source_name",
    "line_number",
    "raw_text",
    "date",
    "time",
    "pid",
    "level",
    "component",
    "message",
    "parse_ok",
    "ts",
    "block_id",
    "size",
    "src_ip",
    "dest_ip",
    "any_ip",
    "event_type",
    "signature",
    "criticality",
    "x_level",
    "x_kb_base",
    "x_lex",
    "x_ctx",
    "x_param",
]

SORT_COLUMNS = {
    "id": "id",
    "line_number": "line_number",
    "source_name": "source_name",
    "ts": "ts",
    "level": "level",
    "event_type": "event_type",
    "component": "component",
    "criticality": "criticality",
    "created_at": "created_at",
    "updated_at": "updated_at",
}

CRITICAL_CONDITION = "(criticality >= 0.7 OR level IN ('ERROR', 'FATAL'))"


def _clean(value: Any) -> Any:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except TypeError:
        pass
    if hasattr(value, "item"):
        return value.item()
    return value


def _clean_text(value: Any, default: str = "") -> str:
    value = _clean(value)
    if value is None:
        return default
    return str(value)


def _clean_int(value: Any) -> int | None:
    value = _clean(value)
    if value is None:
        return None
    return int(value)


def _clean_float(value: Any) -> float:
    value = _clean(value)
    if value is None:
        return 0.0
    return float(value)


def _timestamp_to_text(value: Any) -> str | None:
    value = _clean(value)
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat(sep=" ")
    return str(value)


def _row_to_dict(row: Any) -> dict:
    if row is None:
        return {}
    result = dict(row)
    if "parse_ok" in result:
        result["parse_ok"] = bool(result["parse_ok"])
    for key in ["criticality", "x_level", "x_kb_base", "x_lex", "x_ctx", "x_param"]:
        if key in result and result[key] is not None:
            result[key] = round(float(result[key]), 4)
    return result


def _record_from_dataframe_row(
    row: pd.Series,
    *,
    source_id: int | None,
    source_name: str,
    line_number: int | None,
) -> dict:
    return {
        "source_id": source_id,
        "source_name": source_name,
        "line_number": line_number,
        "raw_text": _clean_text(row.get("raw_text") or row.get("message")),
        "date": _clean(row.get("date")),
        "time": _clean(row.get("time")),
        "pid": _clean_int(row.get("pid")),
        "level": _clean(row.get("level")),
        "component": _clean(row.get("component")),
        "message": _clean_text(row.get("message")),
        "parse_ok": 1 if bool(_clean(row.get("parse_ok"))) else 0,
        "ts": _timestamp_to_text(row.get("ts")),
        "block_id": _clean(row.get("block_id")),
        "size": _clean_int(row.get("size")),
        "src_ip": _clean(row.get("src_ip")),
        "dest_ip": _clean(row.get("dest_ip")),
        "any_ip": _clean(row.get("any_ip")),
        "event_type": _clean_text(row.get("event_type"), "other"),
        "signature": _clean_text(row.get("signature")),
        "criticality": _clean_float(row.get("criticality")),
        "x_level": _clean_float(row.get("x_level")),
        "x_kb_base": _clean_float(row.get("x_kb_base")),
        "x_lex": _clean_float(row.get("x_lex")),
        "x_ctx": _clean_float(row.get("x_ctx")),
        "x_param": _clean_float(row.get("x_param")),
    }


def _insert_log(connection, record: dict) -> int:
    placeholders = ", ".join(f":{column}" for column in LOG_INSERT_COLUMNS)
    columns = ", ".join(LOG_INSERT_COLUMNS)
    cursor = connection.execute(
        f"INSERT INTO logs ({columns}) VALUES ({placeholders})",
        record,
    )
    return int(cursor.lastrowid)


def _bulk_insert_logs(connection, records: list[dict]) -> None:
    if not records:
        return
    placeholders = ", ".join(f":{column}" for column in LOG_INSERT_COLUMNS)
    columns = ", ".join(LOG_INSERT_COLUMNS)
    connection.executemany(
        f"INSERT INTO logs ({columns}) VALUES ({placeholders})",
        records,
    )


def _build_where(
    *,
    search: str | None = None,
    source_name: str | None = None,
    level: str | None = None,
    event_type: str | None = None,
    component: str | None = None,
    min_criticality: float | None = None,
    critical_only: bool = False,
) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []

    if search:
        like = f"%{search.strip()}%"
        clauses.append(
            "(raw_text LIKE ? OR message LIKE ? OR component LIKE ? OR source_name LIKE ? OR signature LIKE ?)"
        )
        params.extend([like, like, like, like, like])
    if source_name:
        clauses.append("source_name = ?")
        params.append(source_name)
    if level:
        clauses.append("level = ?")
        params.append(level)
    if event_type:
        clauses.append("event_type = ?")
        params.append(event_type)
    if component:
        clauses.append("component LIKE ?")
        params.append(f"%{component.strip()}%")
    if min_criticality is not None:
        clauses.append("criticality >= ?")
        params.append(float(min_criticality))
    if critical_only:
        clauses.append(CRITICAL_CONDITION)

    if not clauses:
        return "", params
    return "WHERE " + " AND ".join(clauses), params


def _append_condition(where_sql: str, condition: str) -> str:
    if where_sql:
        return f"{where_sql} AND {condition}"
    return f"WHERE {condition}"


def get_log(log_id: int) -> dict | None:
    with get_connection() as connection:
        row = connection.execute("SELECT * FROM logs WHERE id = ?", (log_id,)).fetchone()
        return _row_to_dict(row) if row else None


def list_logs(
    *,
    page: int = 1,
    page_size: int = 100,
    search: str | None = None,
    source_name: str | None = None,
    level: str | None = None,
    event_type: str | None = None,
    component: str | None = None,
    min_criticality: float | None = None,
    critical_only: bool = False,
    sort_by: str = "criticality",
    sort_order: str = "desc",
) -> dict:
    page = max(page, 1)
    page_size = min(max(page_size, 1), 500)
    sort_column = SORT_COLUMNS.get(sort_by, "criticality")
    order = "ASC" if sort_order.lower() == "asc" else "DESC"
    offset = (page - 1) * page_size
    where_sql, params = _build_where(
        search=search,
        source_name=source_name,
        level=level,
        event_type=event_type,
        component=component,
        min_criticality=min_criticality,
        critical_only=critical_only,
    )

    with get_connection() as connection:
        total = connection.execute(f"SELECT COUNT(*) FROM logs {where_sql}", params).fetchone()[0]
        rows = connection.execute(
            f"""
            SELECT *
            FROM logs
            {where_sql}
            ORDER BY {sort_column} {order}, id DESC
            LIMIT ? OFFSET ?
            """,
            [*params, page_size, offset],
        ).fetchall()

    return {
        "total": int(total),
        "page": page,
        "page_size": page_size,
        "rows": [_row_to_dict(row) for row in rows],
    }


def create_log(raw_text: str, source_name: str = "manual") -> dict:
    raw_text = raw_text.strip("\n")
    if not raw_text.strip():
        raise ValueError("Текст лога не должен быть пустым")

    df = analyze_lines([raw_text])
    record = _record_from_dataframe_row(
        df.iloc[0],
        source_id=None,
        source_name=source_name.strip() or "manual",
        line_number=None,
    )

    with get_connection() as connection:
        log_id = _insert_log(connection, record)

    created = get_log(log_id)
    if created is None:
        raise RuntimeError("Лог был создан, но не найден в базе")
    return created


def update_log(log_id: int, *, raw_text: str | None = None, source_name: str | None = None) -> dict | None:
    existing = get_log(log_id)
    if existing is None:
        return None
    if raw_text is None and source_name is None:
        raise ValueError("Передайте raw_text или source_name для обновления")

    if raw_text is None:
        with get_connection() as connection:
            connection.execute(
                "UPDATE logs SET source_name = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                ((source_name or existing["source_name"]).strip() or "manual", log_id),
            )
        return get_log(log_id)

    raw_text = raw_text.strip("\n")
    if not raw_text.strip():
        raise ValueError("Текст лога не должен быть пустым")

    df = analyze_lines([raw_text])
    record = _record_from_dataframe_row(
        df.iloc[0],
        source_id=existing.get("source_id"),
        source_name=(source_name or existing["source_name"]).strip() or "manual",
        line_number=existing.get("line_number"),
    )

    assignments = ", ".join(f"{column} = :{column}" for column in LOG_INSERT_COLUMNS)
    record["id"] = log_id
    with get_connection() as connection:
        connection.execute(
            f"""
            UPDATE logs
            SET {assignments}, updated_at = CURRENT_TIMESTAMP
            WHERE id = :id
            """,
            record,
        )
    return get_log(log_id)


def delete_log(log_id: int) -> bool:
    with get_connection() as connection:
        cursor = connection.execute("DELETE FROM logs WHERE id = ?", (log_id,))
        return cursor.rowcount > 0


def list_sources() -> list[dict]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                s.*,
                COUNT(l.id) AS db_log_count
            FROM log_sources s
            LEFT JOIN logs l ON l.source_id = s.id
            GROUP BY s.id
            ORDER BY s.name
            """
        ).fetchall()
    return [_row_to_dict(row) for row in rows]


def get_filter_options() -> dict:
    with get_connection() as connection:
        levels = [
            row[0]
            for row in connection.execute(
                "SELECT DISTINCT level FROM logs WHERE level IS NOT NULL ORDER BY level"
            ).fetchall()
        ]
        event_types = [
            row[0]
            for row in connection.execute(
                "SELECT DISTINCT event_type FROM logs WHERE event_type IS NOT NULL ORDER BY event_type"
            ).fetchall()
        ]
        sources = [
            row[0]
            for row in connection.execute(
                "SELECT DISTINCT source_name FROM logs WHERE source_name IS NOT NULL ORDER BY source_name"
            ).fetchall()
        ]
    return {"levels": levels, "event_types": event_types, "sources": sources}


def _file_modified_at(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(timespec="seconds")


def import_data_folder(data_dir: Path, *, dataset_name: str | None = None, force: bool = False) -> dict:
    if dataset_name:
        candidate = data_dir / dataset_name
        if candidate.parent.resolve() != data_dir.resolve() or candidate.suffix != ".log" or not candidate.exists():
            raise ValueError("Датасет не найден в папке data")
        paths = [candidate]
    else:
        paths = sorted(data_dir.glob("*.log"))

    result = {
        "data_dir": str(data_dir),
        "force": force,
        "imported": [],
        "skipped": [],
        "errors": [],
    }

    with get_connection() as connection:
        for path in paths:
            savepoint = "sync_one_file"
            connection.execute(f"SAVEPOINT {savepoint}")
            try:
                stat = path.stat()
                modified_at = _file_modified_at(path)
                source = connection.execute(
                    "SELECT * FROM log_sources WHERE path = ?",
                    (str(path),),
                ).fetchone()

                if (
                    source
                    and not force
                    and int(source["size_bytes"]) == stat.st_size
                    and source["modified_at"] == modified_at
                    and int(source["line_count"]) > 0
                ):
                    result["skipped"].append(
                        {
                            "name": path.name,
                            "reason": "already_synced",
                            "line_count": int(source["line_count"]),
                        }
                    )
                    connection.execute(f"RELEASE {savepoint}")
                    continue

                if source:
                    source_id = int(source["id"])
                    connection.execute("DELETE FROM logs WHERE source_id = ?", (source_id,))
                    connection.execute(
                        """
                        UPDATE log_sources
                        SET name = ?, size_bytes = ?, modified_at = ?, imported_at = CURRENT_TIMESTAMP, line_count = 0
                        WHERE id = ?
                        """,
                        (path.name, stat.st_size, modified_at, source_id),
                    )
                else:
                    cursor = connection.execute(
                        """
                        INSERT INTO log_sources (name, path, size_bytes, modified_at, line_count)
                        VALUES (?, ?, ?, ?, 0)
                        """,
                        (path.name, str(path), stat.st_size, modified_at),
                    )
                    source_id = int(cursor.lastrowid)

                df = analyze_path(path)
                records = [
                    _record_from_dataframe_row(
                        row,
                        source_id=source_id,
                        source_name=path.name,
                        line_number=index + 1,
                    )
                    for index, (_, row) in enumerate(df.iterrows())
                ]
                _bulk_insert_logs(connection, records)
                connection.execute(
                    """
                    UPDATE log_sources
                    SET line_count = ?, imported_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (len(records), source_id),
                )
                result["imported"].append(
                    {
                        "name": path.name,
                        "line_count": len(records),
                        "size_bytes": stat.st_size,
                    }
                )
                connection.execute(f"RELEASE {savepoint}")
            except Exception as exc:
                connection.execute(f"ROLLBACK TO {savepoint}")
                connection.execute(f"RELEASE {savepoint}")
                result["errors"].append({"name": path.name, "error": str(exc)})

    result["imported_count"] = len(result["imported"])
    result["skipped_count"] = len(result["skipped"])
    result["error_count"] = len(result["errors"])
    return result


def get_database_overview() -> dict:
    with get_connection() as connection:
        total_logs = connection.execute("SELECT COUNT(*) FROM logs").fetchone()[0]
        total_sources = connection.execute("SELECT COUNT(*) FROM log_sources").fetchone()[0]
        critical_logs = connection.execute(
            f"SELECT COUNT(*) FROM logs WHERE {CRITICAL_CONDITION}"
        ).fetchone()[0]
    return {
        "total_logs": int(total_logs),
        "total_sources": int(total_sources),
        "critical_logs": int(critical_logs),
    }


def get_log_stats(
    *,
    search: str | None = None,
    source_name: str | None = None,
    level: str | None = None,
    event_type: str | None = None,
    component: str | None = None,
    min_criticality: float | None = None,
    critical_only: bool = False,
    limit: int = 10,
) -> dict:
    limit = min(max(limit, 1), 50)
    where_sql, params = _build_where(
        search=search,
        source_name=source_name,
        level=level,
        event_type=event_type,
        component=component,
        min_criticality=min_criticality,
        critical_only=critical_only,
    )

    with get_connection() as connection:
        summary_row = connection.execute(
            f"""
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN {CRITICAL_CONDITION} THEN 1 ELSE 0 END) AS critical_count,
                SUM(CASE WHEN level = 'WARN' THEN 1 ELSE 0 END) AS warn_count,
                SUM(CASE WHEN level IN ('ERROR', 'FATAL') THEN 1 ELSE 0 END) AS error_count,
                AVG(criticality) AS avg_criticality,
                MIN(criticality) AS min_criticality,
                MAX(criticality) AS max_criticality
            FROM logs
            {where_sql}
            """,
            params,
        ).fetchone()

        levels = [
            {"level": row["level"] or "unknown", "count": int(row["count"])}
            for row in connection.execute(
                f"""
                SELECT level, COUNT(*) AS count
                FROM logs
                {where_sql}
                GROUP BY level
                ORDER BY count DESC
                """,
                params,
            ).fetchall()
        ]

        event_types = [
            {"event_type": row["event_type"] or "unknown", "count": int(row["count"])}
            for row in connection.execute(
                f"""
                SELECT event_type, COUNT(*) AS count
                FROM logs
                {where_sql}
                GROUP BY event_type
                ORDER BY count DESC
                LIMIT ?
                """,
                [*params, limit],
            ).fetchall()
        ]

        component_condition = "component IS NOT NULL AND component <> ''"
        component_where = _append_condition(where_sql, component_condition)
        problem_components = [
            {
                "component": row["component"],
                "total": int(row["total"]),
                "critical_count": int(row["critical_count"] or 0),
                "avg_criticality": round(float(row["avg_criticality"] or 0), 4),
                "max_criticality": round(float(row["max_criticality"] or 0), 4),
            }
            for row in connection.execute(
                f"""
                SELECT
                    component,
                    COUNT(*) AS total,
                    SUM(CASE WHEN {CRITICAL_CONDITION} THEN 1 ELSE 0 END) AS critical_count,
                    AVG(criticality) AS avg_criticality,
                    MAX(criticality) AS max_criticality
                FROM logs
                {component_where}
                GROUP BY component
                HAVING critical_count > 0 OR avg_criticality >= 0.45
                ORDER BY critical_count DESC, avg_criticality DESC, total DESC
                LIMIT ?
                """,
                [*params, limit],
            ).fetchall()
        ]

        repeated_where = _append_condition(
            where_sql,
            "(signature IS NOT NULL AND signature <> '' AND (level IN ('WARN', 'ERROR', 'FATAL') OR criticality >= 0.6 OR message LIKE '%error%' OR message LIKE '%failed%' OR message LIKE '%exception%'))",
        )
        repeated_errors = [
            {
                "signature": row["signature"],
                "component": row["component"] or "unknown",
                "event_type": row["event_type"] or "unknown",
                "levels": row["levels"] or "",
                "count": int(row["count"]),
                "avg_criticality": round(float(row["avg_criticality"] or 0), 4),
                "max_criticality": round(float(row["max_criticality"] or 0), 4),
                "sample_id": int(row["sample_id"]),
                "sample_message": row["sample_message"] or "",
            }
            for row in connection.execute(
                f"""
                SELECT
                    signature,
                    component,
                    event_type,
                    GROUP_CONCAT(DISTINCT level) AS levels,
                    COUNT(*) AS count,
                    AVG(criticality) AS avg_criticality,
                    MAX(criticality) AS max_criticality,
                    MIN(id) AS sample_id,
                    MIN(message) AS sample_message
                FROM logs
                {repeated_where}
                GROUP BY signature, component, event_type
                HAVING count > 1
                ORDER BY count DESC, max_criticality DESC
                LIMIT ?
                """,
                [*params, limit],
            ).fetchall()
        ]

        critical_where = _append_condition(where_sql, CRITICAL_CONDITION)
        critical_rows = [
            _row_to_dict(row)
            for row in connection.execute(
                f"""
                SELECT *
                FROM logs
                {critical_where}
                ORDER BY criticality DESC, id DESC
                LIMIT ?
                """,
                [*params, limit],
            ).fetchall()
        ]

    summary = _row_to_dict(summary_row)
    return {
        "summary": {
            "total": int(summary.get("total") or 0),
            "critical_count": int(summary.get("critical_count") or 0),
            "warn_count": int(summary.get("warn_count") or 0),
            "error_count": int(summary.get("error_count") or 0),
            "avg_criticality": round(float(summary.get("avg_criticality") or 0), 4),
            "min_criticality": round(float(summary.get("min_criticality") or 0), 4),
            "max_criticality": round(float(summary.get("max_criticality") or 0), 4),
        },
        "levels": levels,
        "event_types": event_types,
        "problem_components": problem_components,
        "repeated_errors": repeated_errors,
        "critical_rows": critical_rows,
    }
