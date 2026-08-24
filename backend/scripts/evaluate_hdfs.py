"""Экспериментальная валидация нечёткой оценки критичности на HDFS.

Считает AUC-ROC и Average Precision, сопоставляя оценку критичности модели
Мамдани с ОФИЦИАЛЬНОЙ разметкой аномалий LogHub HDFS_v1 (метки Normal/Anomaly
по block_id из loglizer/loghub), а не с прокси-меткой WARN.

Разметка (data/hdfs_anomaly_label.csv) — ground truth: каждому blk_<id>
экспертами присвоена метка normal/anomaly. Модель критичности при этом
строится без обучающих данных (правила задаются экспертами) — размеченная
выборка нужна только для этой процедуры проверки.

Запуск:
    python backend/scripts/evaluate_hdfs.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import (
    average_precision_score,
    confusion_matrix,
    f1_score,
    roc_auc_score,
    roc_curve,
)

# --- подключаем модель из проекта ---
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from app.core.log_model import analyze_lines  # noqa: E402

LOG_PATH = ROOT / "data" / "HDFS_2k.log"
LABEL_PATH = ROOT / "data" / "hdfs_anomaly_label.csv"


def best_threshold(y_true: np.ndarray, y_score: np.ndarray) -> tuple[float, float, float, float]:
    """Порог по Youden J (TPR-FPR) и по максимуму F1 на сетке."""
    fpr, tpr, thr = roc_curve(y_true, y_score)
    j = tpr - fpr
    ix = int(np.argmax(j))
    thr_j = float(thr[ix])

    best_f1, thr_f1 = 0.0, 0.5
    for t in np.linspace(0, 1, 501):
        f = f1_score(y_true, (y_score >= t).astype(int), zero_division=0)
        if f > best_f1:
            best_f1, thr_f1 = f, float(t)
    return thr_j, float(j[ix]), thr_f1, best_f1


def report(name: str, y_true: np.ndarray, y_score: np.ndarray) -> None:
    auc = roc_auc_score(y_true, y_score)
    ap = average_precision_score(y_true, y_score)
    thr_j, jmax, thr_f1, best_f1 = best_threshold(y_true, y_score)

    print(f"\n===== {name} =====")
    print(f"  объектов: {len(y_true)}  (Anomaly={int(y_true.sum())}, "
          f"Normal={int((1 - y_true).sum())}, доля аномалий={y_true.mean():.3%})")
    print(f"  AUC-ROC            = {auc:.4f}")
    print(f"  Average Precision  = {ap:.4f}")
    print(f"  Порог по Youden J  = {thr_j:.4f}  (Jmax={jmax:.4f})")
    print(f"  Порог по max F1    = {thr_f1:.4f}  (F1={best_f1:.4f})")
    for thr, label in [(thr_j, "Youden"), (thr_f1, "max F1")]:
        pred = (y_score >= thr).astype(int)
        tn, fp, fn, tp = confusion_matrix(y_true, pred, labels=[0, 1]).ravel()
        prec = tp / (tp + fp) if (tp + fp) else 0.0
        rec = tp / (tp + fn) if (tp + fn) else 0.0
        print(f"    [{label} thr={thr:.3f}] TP={tp} FP={fp} FN={fn} TN={tn} "
              f"precision={prec:.3f} recall={rec:.3f}")


def main() -> None:
    if not LABEL_PATH.exists():
        raise SystemExit(f"Нет файла разметки: {LABEL_PATH}")

    lines = LOG_PATH.read_text(encoding="utf-8", errors="ignore").splitlines()
    df = analyze_lines(lines)
    df = df[df["block_id"].notna()].copy()
    df["block_id"] = "blk_" + df["block_id"].astype(str)

    labels = pd.read_csv(LABEL_PATH)
    label_map = dict(zip(labels["BlockId"], labels["Label"]))
    df["y_true"] = df["block_id"].map(label_map)
    df = df[df["y_true"].notna()].copy()
    df["y_true"] = (df["y_true"] == "Anomaly").astype(int)

    print(f"Источник логов : {LOG_PATH.name}  ({len(lines)} строк)")
    print(f"Разметка       : {LABEL_PATH.name}  (LogHub HDFS_v1, официальная)")
    print(f"Строк с блоком, покрытых разметкой: {len(df)}")

    # --- Уровень БЛОКА (стандартная для HDFS постановка) ---
    grp = df.groupby("block_id").agg(
        y_true=("y_true", "max"),
        score_max=("criticality", "max"),
        score_mean=("criticality", "mean"),
    )
    report("Блочный уровень (score = max критичность по блоку)",
           grp["y_true"].to_numpy(), grp["score_max"].to_numpy())
    report("Блочный уровень (score = средняя критичность по блоку)",
           grp["y_true"].to_numpy(), grp["score_mean"].to_numpy())

    # --- Уровень СТРОКИ (метка блока распространена на его строки) ---
    report("Строчный уровень (метка блока → строкам)",
           df["y_true"].to_numpy(), df["criticality"].to_numpy())


if __name__ == "__main__":
    main()
