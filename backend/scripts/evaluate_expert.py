"""Валидация критичности против ЭКСПЕРТНОЙ разметки (путь 3).

Проверяет, согласуется ли автоматическая оценка критичности (нечёткий вывод
Мамдани) с экспертным суждением об операционной тяжести события на
гетерогенной выборке логов пяти систем (HDFS, BGL, Hadoop, Spark, Zookeeper).

Разметка (data/expert_labels.csv): 1 = реальный инцидент/сбой,
0 = рутина/диагностическая телеметрия. Метки проставлены по СМЫСЛУ сообщения
независимо от уровня логирования (см. backend/scripts/expert_labeling.py) —
18% меток расходятся с наивной эвристикой "FATAL/ERROR = инцидент", поэтому
проверка не сводится к тавтологии.

Печатается baseline "только уровень логирования" и bootstrap-доверительные
интервалы: если нечёткая модель по качеству не превосходит порог по уровню,
дополнительные признаки пользы для детекции не приносят.

Запуск:
    python backend/scripts/evaluate_expert.py
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import numpy as np
from sklearn.metrics import (
    average_precision_score,
    confusion_matrix,
    f1_score,
    roc_auc_score,
    roc_curve,
)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from app.core.log_model import (  # noqa: E402
    BAD_MSG_RE,
    KB_BASE_SEVERITY,
    LEVEL_SCORE,
    SIZE_RE,
    STANDARD_BLOCK,
    classify_event,
    criticality_mamdani,
    parse_log_line,
)

LABELS = ROOT / "data" / "expert_labels.csv"


def features(raw: str) -> tuple[float, float, float, float, float]:
    """Пять признаков модели для одиночного события (x_ctx=0: события
    изолированы, скользящее окно не определено)."""
    rec = parse_log_line(raw)
    message = rec["message"] or ""
    x_level = LEVEL_SCORE.get(rec["level"], 0.2)
    x_kb = KB_BASE_SEVERITY.get(classify_event(message), 0.15)
    x_lex = 1.0 if BAD_MSG_RE.search(message) else 0.0
    m = SIZE_RE.search(message)
    if m and float(m.group(1)) != STANDARD_BLOCK:
        x_param = min(abs(float(m.group(1)) - STANDARD_BLOCK) / STANDARD_BLOCK, 1.0)
    else:
        x_param = 0.0
    return x_level, x_kb, x_lex, 0.0, x_param


def bootstrap_ci(y: np.ndarray, s: np.ndarray, fn, n_iter: int = 2000, seed: int = 0):
    rng = np.random.default_rng(seed)
    vals = []
    for _ in range(n_iter):
        idx = rng.integers(0, len(y), len(y))
        if 0 < y[idx].sum() < len(idx):
            vals.append(fn(y[idx], s[idx]))
    return float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))


def report(name: str, y: np.ndarray, s: np.ndarray) -> None:
    auc = roc_auc_score(y, s)
    ap = average_precision_score(y, s)
    auc_lo, auc_hi = bootstrap_ci(y, s, roc_auc_score)
    ap_lo, ap_hi = bootstrap_ci(y, s, average_precision_score)
    fpr, tpr, thr = roc_curve(y, s)
    ix = int(np.argmax(tpr - fpr))
    thr_j = float(thr[ix])
    best_f1 = max(f1_score(y, (s >= t).astype(int), zero_division=0) for t in np.linspace(0, 1, 501))
    tn, fp, fn, tp = confusion_matrix(y, (s >= thr_j).astype(int), labels=[0, 1]).ravel()
    print(f"\n===== {name} =====")
    print(f"  AUC-ROC           = {auc:.3f}   95% CI [{auc_lo:.3f}, {auc_hi:.3f}]")
    print(f"  Average Precision = {ap:.3f}   95% CI [{ap_lo:.3f}, {ap_hi:.3f}]")
    print(f"  Порог Youden J    = {thr_j:.3f} → TP={tp} FP={fp} FN={fn} TN={tn} "
          f"(precision={tp/(tp+fp):.2f}, recall={tp/(tp+fn):.2f})")
    print(f"  Лучший F1         = {best_f1:.3f}")


def main() -> None:
    rows = list(csv.DictReader(LABELS.open(encoding="utf-8")))
    y = np.array([int(r["label"]) for r in rows])
    crit = np.array([criticality_mamdani(*features(r["raw_line"])) for r in rows])
    level_only = np.array([LEVEL_SCORE.get(parse_log_line(r["raw_line"])["level"], 0.2) for r in rows])
    print(f"Выборка: {len(rows)} событий (инцидентов={int(y.sum())}, рутина={int((1 - y).sum())})")
    print(f"Источник: {LABELS.name} — гетерогенная экспертная разметка (HDFS/BGL/Hadoop/Spark/Zookeeper)")
    report("Нечёткая критичность (5 признаков, Мамдани)", y, crit)
    report("Baseline: только уровень логирования", y, level_only)


if __name__ == "__main__":
    main()
