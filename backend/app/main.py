from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Literal
from uuid import uuid4

import pandas as pd
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.core.log_model import analyze_path, analyze_text, build_summary, dataframe_to_csv_buffer, serialize_rows

ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT_DIR / "data"

app = FastAPI(title="LogFuzzy API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ANALYSES: dict[str, dict] = {}


class DatasetAnalyzeRequest(BaseModel):
    dataset_name: str


class TextAnalyzeRequest(BaseModel):
    text: str
    source_name: str = "manual_input.log"


def list_dataset_paths() -> list[Path]:
    return sorted(DATA_DIR.glob("*.log"))


def get_analysis_or_404(analysis_id: str) -> dict:
    analysis = ANALYSES.get(analysis_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="Анализ не найден")
    return analysis


def create_analysis(df: pd.DataFrame, source_name: str) -> dict:
    analysis_id = str(uuid4())
    summary = build_summary(df, source_name)
    ANALYSES[analysis_id] = {
        "id": analysis_id,
        "source_name": source_name,
        "df": df,
        "summary": summary,
    }
    return {
        "analysis_id": analysis_id,
        "source_name": source_name,
        "summary": summary,
    }


@app.get("/health")
def healthcheck() -> dict:
    return {"status": "ok"}


@app.get("/datasets")
def list_datasets() -> dict:
    datasets = []
    for path in list_dataset_paths():
        datasets.append(
            {
                "name": path.name,
                "size_bytes": path.stat().st_size,
            }
        )
    return {"datasets": datasets}


@app.post("/analyze/dataset")
def analyze_dataset(payload: DatasetAnalyzeRequest) -> dict:
    path = DATA_DIR / payload.dataset_name
    if not path.exists() or path.suffix != ".log":
        raise HTTPException(status_code=404, detail="Датасет не найден")

    df = analyze_path(path)
    return create_analysis(df, payload.dataset_name)


@app.post("/analyze/text")
def analyze_manual_text(payload: TextAnalyzeRequest) -> dict:
    if not payload.text.strip():
        raise HTTPException(status_code=400, detail="Текст логов пустой")

    df = analyze_text(payload.text)
    return create_analysis(df, payload.source_name)


@app.post("/analyze/upload")
async def analyze_upload(file: UploadFile = File(...)) -> dict:
    content = await file.read()
    text = content.decode("utf-8", errors="ignore")
    if not text.strip():
        raise HTTPException(status_code=400, detail="Файл пустой")

    df = analyze_text(text)
    return create_analysis(df, file.filename or "uploaded.log")


@app.get("/analyses/{analysis_id}/summary")
def get_summary(analysis_id: str) -> dict:
    analysis = get_analysis_or_404(analysis_id)
    return {
        "analysis_id": analysis_id,
        "source_name": analysis["source_name"],
        "summary": analysis["summary"],
    }


@app.get("/analyses/{analysis_id}/rows")
def get_rows(
    analysis_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    level: str | None = None,
    event_type: str | None = None,
    component: str | None = None,
    search: str | None = None,
    sort_by: Literal["criticality", "ts", "level", "event_type", "component", "row_id"] = "criticality",
    sort_order: Literal["asc", "desc"] = "desc",
) -> dict:
    analysis = get_analysis_or_404(analysis_id)
    df = analysis["df"]

    filtered = df
    if level:
        filtered = filtered[filtered["level"] == level]
    if event_type:
        filtered = filtered[filtered["event_type"] == event_type]
    if component:
        filtered = filtered[filtered["component"].astype(str).str.contains(component, case=False, na=False)]
    if search:
        filtered = filtered[
            filtered["message"].astype(str).str.contains(search, case=False, na=False)
            | filtered["component"].astype(str).str.contains(search, case=False, na=False)
        ]

    ascending = sort_order == "asc"
    filtered = filtered.sort_values(sort_by, ascending=ascending, na_position="last")

    total = len(filtered)
    start = (page - 1) * page_size
    end = start + page_size
    page_df = filtered.iloc[start:end]

    return {
        "analysis_id": analysis_id,
        "total": int(total),
        "page": page,
        "page_size": page_size,
        "rows": serialize_rows(page_df),
    }


@app.get("/analyses/{analysis_id}/download")
def download_csv(analysis_id: str) -> StreamingResponse:
    analysis = get_analysis_or_404(analysis_id)
    buffer = dataframe_to_csv_buffer(analysis["df"])
    filename = analysis["source_name"].rsplit(".", 1)[0] + "_criticality.csv"
    return StreamingResponse(
        BytesIO(buffer.getvalue().encode("utf-8")),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
