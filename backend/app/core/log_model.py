from __future__ import annotations

import io
import re
from pathlib import Path

import numpy as np
import pandas as pd

LOG_LINE_RE = re.compile(
    r"^(\d{6})\s+(\d{6})\s+(\d+)\s+(INFO|WARN|ERROR|DEBUG|FATAL)\s+(.+)$"
)
BLOCK_RE = re.compile(r"\bblk_(-?\d+)\b")
SIZE_RE = re.compile(r"\bsize\s+(\d+)\b")
SRC_IP_RE = re.compile(r"\bsrc:\s*/(\d{1,3}(?:\.\d{1,3}){3})")
DEST_IP_RE = re.compile(r"\bdest:\s*/(\d{1,3}(?:\.\d{1,3}){3})")
ANY_IP_RE = re.compile(r"/(\d{1,3}(?:\.\d{1,3}){3})")
BAD_MSG_RE = re.compile(
    r"exception|failed|failure|error|corrupt|timeout|denied|unavailable|abort",
    re.IGNORECASE,
)
NUMBER_RE = re.compile(r"\b\d+\b")
WHITESPACE_RE = re.compile(r"\s+")

EVENT_PATTERNS = [
    ("warn_exception_serving", r"Got exception while serving"),
    ("block_received", r"\bReceived block\b"),
    ("block_receiving", r"\bReceiving block\b"),
    ("block_served", r"\bServed block\b"),
    ("allocate_block", r"NameSystem\.allocateBlock"),
    ("add_stored_block", r"NameSystem\.addStoredBlock"),
    ("packet_responder_terminating", r"PacketResponder .* terminating"),
    ("verification_succeeded", r"Verification succeeded"),
    ("deleting_block", r"\bDeleting block\b"),
]

KB_BASE_SEVERITY = {
    "warn_exception_serving": 0.95,
    "deleting_block": 0.28,
    "block_served": 0.18,
    "block_received": 0.12,
    "block_receiving": 0.12,
    "add_stored_block": 0.08,
    "allocate_block": 0.08,
    "packet_responder_terminating": 0.06,
    "verification_succeeded": 0.04,
    "other": 0.15,
}

LEVEL_SCORE = {"DEBUG": 0.05, "INFO": 0.12, "WARN": 0.72, "ERROR": 0.92, "FATAL": 1.0}
STANDARD_BLOCK = 67108864

IN_LOW = (0.0, 0.0, 0.38)
IN_MED = (0.22, 0.5, 0.78)
IN_HIGH = (0.55, 1.0, 1.0)
Z = np.linspace(0.0, 1.0, 121)


def trimf_scalar(x: float, abc: tuple[float, float, float]) -> float:
    a, b, c = abc
    x = float(np.clip(x, 0.0, 1.0))
    if x <= a or x >= c:
        return 0.0
    if x < b:
        return 0.0 if b == a else (x - a) / (b - a)
    return 0.0 if c == b else (c - x) / (c - b)


def trimf_vec(z: np.ndarray, abc: tuple[float, float, float]) -> np.ndarray:
    a, b, c = abc
    y = np.zeros_like(z, dtype=float)
    m1 = (z >= a) & (z <= b)
    m2 = (z >= b) & (z <= c)
    y[m1] = (z[m1] - a) / max(b - a, 1e-9)
    y[m2] = (c - z[m2]) / max(c - b, 1e-9)
    return np.clip(y, 0.0, 1.0)


OUT_LOW = trimf_vec(Z, (0.0, 0.0, 0.38))
OUT_MED = trimf_vec(Z, (0.25, 0.5, 0.75))
OUT_HIGH = trimf_vec(Z, (0.55, 1.0, 1.0))


def build_error_signature(message: str | None) -> str:
    """Normalize volatile values so repeated errors can be grouped."""
    text = str(message or "").strip().lower()
    text = re.sub(BLOCK_RE, "blk_<id>", text)
    text = re.sub(ANY_IP_RE, "/<ip>", text)
    text = re.sub(NUMBER_RE, "<num>", text)
    text = WHITESPACE_RE.sub(" ", text)
    return text[:500] or "empty"


def parse_log_line(line: str) -> dict:
    match = LOG_LINE_RE.match(line)
    if not match:
        return {
            "raw_text": line,
            "date": None,
            "time": None,
            "pid": None,
            "level": None,
            "component": None,
            "message": line,
            "parse_ok": False,
        }

    date, time, pid, level, rest = match.groups()
    if ": " in rest:
        component, message = rest.split(": ", 1)
    else:
        idx = rest.find(":")
        if idx != -1:
            component, message = rest[:idx], rest[idx + 1 :].lstrip()
        else:
            component, message = rest, ""

    return {
        "raw_text": line,
        "date": date,
        "time": time,
        "pid": int(pid),
        "level": level,
        "component": component,
        "message": message,
        "parse_ok": True,
    }


def classify_event(message: str | None) -> str:
    if message is None:
        return "unknown"
    for name, pattern in EVENT_PATTERNS:
        if re.search(pattern, message):
            return name
    return "other"


def to_timestamp(date_yyMMdd: str | None, time_hhmmss: str | None) -> pd.Timestamp | pd.NaT:
    # Be defensive: inputs may be None, NaN (float) or non-standard strings.
    if not date_yyMMdd or not time_hhmmss:
        return pd.NaT

    try:
        s_date = str(date_yyMMdd)
        s_time = str(time_hhmmss)
        if len(s_date) < 6 or len(s_time) < 6:
            return pd.NaT
        # ensure we have digits where expected
        if not (s_date[:6].isdigit() and s_time[:6].isdigit()):
            return pd.NaT

        yy = int(s_date[:2])
        mm = int(s_date[2:4])
        dd = int(s_date[4:6])
        hh = int(s_time[:2])
        minute = int(s_time[2:4])
        ss = int(s_time[4:6])
        return pd.Timestamp(year=2000 + yy, month=mm, day=dd, hour=hh, minute=minute, second=ss)
    except Exception:
        return pd.NaT


def criticality_mamdani(x_level: float, x_kb: float, x_lex: float, x_ctx: float, x_param: float) -> float:
    low_level, _, high_level = (
        trimf_scalar(x_level, IN_LOW),
        trimf_scalar(x_level, IN_MED),
        trimf_scalar(x_level, IN_HIGH),
    )
    low_kb, _, high_kb = (
        trimf_scalar(x_kb, IN_LOW),
        trimf_scalar(x_kb, IN_MED),
        trimf_scalar(x_kb, IN_HIGH),
    )
    low_lex, _, high_lex = (
        trimf_scalar(x_lex, IN_LOW),
        trimf_scalar(x_lex, IN_MED),
        trimf_scalar(x_lex, IN_HIGH),
    )
    low_ctx, _, high_ctx = (
        trimf_scalar(x_ctx, IN_LOW),
        trimf_scalar(x_ctx, IN_MED),
        trimf_scalar(x_ctx, IN_HIGH),
    )
    low_param, _, high_param = (
        trimf_scalar(x_param, IN_LOW),
        trimf_scalar(x_param, IN_MED),
        trimf_scalar(x_param, IN_HIGH),
    )

    agg = np.zeros_like(Z)

    activation = max(high_level, high_lex)
    agg = np.maximum(agg, np.minimum(activation, OUT_HIGH))

    activation = high_kb
    agg = np.maximum(agg, np.minimum(activation, OUT_HIGH))

    activation = high_ctx
    agg = np.maximum(agg, np.minimum(activation, OUT_MED))

    activation = high_param
    agg = np.maximum(agg, np.minimum(activation, OUT_MED))

    activation = min(low_level, low_kb, low_lex, low_ctx, low_param)
    agg = np.maximum(agg, np.minimum(activation, OUT_LOW))

    total = agg.sum()
    if total < 1e-9:
        return float(
            np.clip(
                0.22 * x_level + 0.28 * x_kb + 0.35 * x_lex + 0.15 * x_ctx + 0.1 * x_param,
                0,
                1,
            )
        )
    return float(np.sum(Z * agg) / total)


def analyze_lines(lines: list[str]) -> pd.DataFrame:
    raw_lines = [line.rstrip("\n") for line in lines if line.strip()]
    df = pd.DataFrame([parse_log_line(line) for line in raw_lines])
    df["row_id"] = np.arange(1, len(df) + 1)
    df["ts"] = [
        to_timestamp(date, time)
        for date, time in zip(df["date"].astype(str), df["time"].astype(str), strict=False)
    ]
    df["block_id"] = df["message"].str.extract(BLOCK_RE, expand=False)
    df["size"] = pd.to_numeric(df["message"].str.extract(SIZE_RE, expand=False), errors="coerce")
    df["src_ip"] = df["message"].str.extract(SRC_IP_RE, expand=False)
    df["dest_ip"] = df["message"].str.extract(DEST_IP_RE, expand=False)
    df["any_ip"] = df["message"].str.extract(ANY_IP_RE, expand=False)
    df["event_type"] = df["message"].apply(classify_event)
    df["signature"] = df["message"].apply(build_error_signature)

    df["x_level"] = df["level"].map(LEVEL_SCORE).fillna(0.2).clip(0, 1)
    df["x_kb_base"] = df["event_type"].map(KB_BASE_SEVERITY).fillna(0.15).clip(0, 1)
    df["x_lex"] = df["message"].astype(str).str.contains(BAD_MSG_RE, na=False).astype(float)

    df_sorted = df.sort_values("ts")
    rolling_warn = df_sorted["level"].eq("WARN").rolling(window=100, min_periods=15).mean()
    df["x_ctx"] = rolling_warn.reindex(df.index).fillna(0.0)

    sizes = pd.to_numeric(df["size"], errors="coerce")
    deviation = (sizes - STANDARD_BLOCK).abs() / STANDARD_BLOCK
    df["x_param"] = np.where(sizes.notna() & (sizes != STANDARD_BLOCK), deviation.clip(0, 1), 0.0)

    df["criticality"] = [
        criticality_mamdani(row.x_level, row.x_kb_base, row.x_lex, row.x_ctx, row.x_param)
        for row in df.itertuples(index=False)
    ]
    return df


def analyze_text(text: str) -> pd.DataFrame:
    return analyze_lines(text.splitlines())


def analyze_path(path: Path) -> pd.DataFrame:
    return analyze_text(path.read_text(encoding="utf-8", errors="ignore"))


def serialize_rows(df: pd.DataFrame) -> list[dict]:
    export_columns = [
        "id",
        "row_id",
        "line_number",
        "source_name",
        "ts",
        "date",
        "time",
        "level",
        "component",
        "event_type",
        "criticality",
        "x_level",
        "x_kb_base",
        "x_lex",
        "x_ctx",
        "x_param",
        "signature",
        "raw_text",
        "message",
    ]
    rows: list[dict] = []
    available_columns = [column for column in export_columns if column in df.columns]
    for record in df[available_columns].to_dict(orient="records"):
        row = dict(record)
        if "ts" in row:
            row["ts"] = None if pd.isna(row["ts"]) else row["ts"].isoformat(sep=" ")
        for key in ["criticality", "x_level", "x_kb_base", "x_lex", "x_ctx", "x_param"]:
            if key in row:
                row[key] = round(float(row[key]), 4)
        rows.append(row)
    return rows


def dataframe_to_csv_buffer(df: pd.DataFrame) -> io.StringIO:
    export_columns = [
        "ts",
        "date",
        "time",
        "level",
        "component",
        "event_type",
        "criticality",
        "x_level",
        "x_kb_base",
        "x_lex",
        "x_ctx",
        "x_param",
        "signature",
        "raw_text",
        "message",
    ]
    csv_buffer = io.StringIO()
    df[[column for column in export_columns if column in df.columns]].to_csv(csv_buffer, index=False)
    csv_buffer.seek(0)
    return csv_buffer


def build_histogram(values: pd.Series, bins: int = 10) -> list[dict]:
    counts, edges = np.histogram(values.fillna(0.0), bins=bins, range=(0.0, 1.0))
    histogram = []
    for index, count in enumerate(counts):
        histogram.append(
            {
                "label": f"{edges[index]:.1f}-{edges[index + 1]:.1f}",
                "count": int(count),
            }
        )
    return histogram


def build_summary(df: pd.DataFrame, source_name: str) -> dict:
    parse_ok_rate = float(df["parse_ok"].mean()) if len(df) else 0.0
    warn_rate = float(df["level"].eq("WARN").mean()) if len(df) else 0.0
    criticality = df["criticality"] if "criticality" in df.columns else pd.Series(dtype=float)
    top_rows = df.sort_values("criticality", ascending=False).head(10)

    return {
        "source_name": source_name,
        "row_count": int(len(df)),
        "parse_ok_rate": round(parse_ok_rate, 4),
        "warn_rate": round(warn_rate, 4),
        "criticality": {
            "min": round(float(criticality.min()), 4) if len(criticality) else 0.0,
            "mean": round(float(criticality.mean()), 4) if len(criticality) else 0.0,
            "median": round(float(criticality.median()), 4) if len(criticality) else 0.0,
            "max": round(float(criticality.max()), 4) if len(criticality) else 0.0,
        },
        "levels": {str(key): int(value) for key, value in df["level"].value_counts(dropna=False).items()},
        "event_types": {
            str(key): int(value) for key, value in df["event_type"].value_counts(dropna=False).head(12).items()
        },
        "top_components": {
            str(key): int(value) for key, value in df["component"].value_counts(dropna=False).head(12).items()
        },
        "histogram": build_histogram(criticality, bins=12),
        "top_rows": serialize_rows(top_rows),
        "filter_options": {
            "levels": sorted(df["level"].dropna().astype(str).unique().tolist()),
            "event_types": sorted(df["event_type"].dropna().astype(str).unique().tolist()),
            "components": sorted(df["component"].dropna().astype(str).unique().tolist())[:200],
        },
    }
