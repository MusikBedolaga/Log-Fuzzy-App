from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, status
from pydantic import BaseModel

from app.db import repository

logger = logging.getLogger(__name__)


def _schedule_index(log_id: int, background_tasks: BackgroundTasks) -> None:
    try:
        from app.recommend.router import index_one_log
        background_tasks.add_task(index_one_log, log_id)
    except Exception as exc:
        logger.debug("Could not schedule embedding for log_id=%s: %s", log_id, exc)


def _delete_embedding(log_id: int) -> None:
    try:
        from app.recommend import pg_store
        pg_store.delete_embedding(log_id)
    except Exception as exc:
        logger.debug("Could not delete embedding for log_id=%s: %s", log_id, exc)


class LogCreateRequest(BaseModel):
    raw_text: str
    source_name: str = "manual"


class LogUpdateRequest(BaseModel):
    raw_text: str | None = None
    source_name: str | None = None


class DataImportRequest(BaseModel):
    dataset_name: str | None = None
    force: bool = False


def create_router(data_dir: Path) -> APIRouter:
    router = APIRouter(prefix="/logs", tags=["logs"])

    @router.get("")
    def list_logs(
        page: int = Query(1, ge=1),
        page_size: int = Query(100, ge=1, le=500),
        search: str | None = None,
        source_name: str | None = None,
        level: str | None = None,
        event_type: str | None = None,
        component: str | None = None,
        min_criticality: float | None = Query(None, ge=0, le=1),
        critical_only: bool = False,
        sort_by: Literal[
            "id",
            "line_number",
            "source_name",
            "ts",
            "level",
            "event_type",
            "component",
            "criticality",
            "created_at",
            "updated_at",
        ] = "criticality",
        sort_order: Literal["asc", "desc"] = "desc",
    ) -> dict:
        return repository.list_logs(
            page=page,
            page_size=page_size,
            search=search,
            source_name=source_name,
            level=level,
            event_type=event_type,
            component=component,
            min_criticality=min_criticality,
            critical_only=critical_only,
            sort_by=sort_by,
            sort_order=sort_order,
        )

    @router.post("", status_code=status.HTTP_201_CREATED)
    def create_log(payload: LogCreateRequest, background_tasks: BackgroundTasks) -> dict:
        try:
            log = repository.create_log(payload.raw_text, payload.source_name)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        _schedule_index(log["id"], background_tasks)
        return log

    @router.post("/import-data")
    def import_data(payload: DataImportRequest) -> dict:
        try:
            return repository.import_data_folder(
                data_dir,
                dataset_name=payload.dataset_name,
                force=payload.force,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/sources")
    def list_sources() -> dict:
        return {"sources": repository.list_sources()}

    @router.get("/filters")
    def get_filter_options() -> dict:
        return repository.get_filter_options()

    @router.get("/stats")
    def get_stats(
        search: str | None = None,
        source_name: str | None = None,
        level: str | None = None,
        event_type: str | None = None,
        component: str | None = None,
        min_criticality: float | None = Query(None, ge=0, le=1),
        critical_only: bool = False,
        limit: int = Query(10, ge=1, le=50),
    ) -> dict:
        return repository.get_log_stats(
            search=search,
            source_name=source_name,
            level=level,
            event_type=event_type,
            component=component,
            min_criticality=min_criticality,
            critical_only=critical_only,
            limit=limit,
        )

    @router.get("/{log_id}")
    def get_log(log_id: int) -> dict:
        log = repository.get_log(log_id)
        if log is None:
            raise HTTPException(status_code=404, detail="Лог не найден")
        return log

    @router.put("/{log_id}")
    def update_log(log_id: int, payload: LogUpdateRequest, background_tasks: BackgroundTasks) -> dict:
        try:
            log = repository.update_log(
                log_id,
                raw_text=payload.raw_text,
                source_name=payload.source_name,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        if log is None:
            raise HTTPException(status_code=404, detail="Лог не найден")
        _schedule_index(log_id, background_tasks)
        return log

    @router.delete("/{log_id}")
    def delete_log(log_id: int) -> dict:
        deleted = repository.delete_log(log_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Лог не найден")
        _delete_embedding(log_id)
        return {"status": "deleted", "id": log_id}

    return router
