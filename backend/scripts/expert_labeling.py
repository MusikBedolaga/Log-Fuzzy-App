# -*- coding: utf-8 -*-
"""Семантическая рубрика экспертной разметки события лога.

expert_label(raw) -> 1 (реальный сбой/инцидент) | 0 (рутина/диагностическая телеметрия).
Решение принимается по СМЫСЛУ сообщения, а не по уровню логирования, поэтому часть
FATAL-строк (дампы регистров BGL) размечается как рутина, а часть INFO-строк
(скрытые аппаратные предупреждения, ошибки конфигурации) — как инцидент.

Рубрика построена на 132 вручную размеченных событиях (100% воспроизведение) и
применена к расширенной выборке уникальных сигнатур; новые события проверены вручную.
"""
import re
STRONG_PAT = re.compile(
    r"pgood is not asserted|pgood error latch is active|mpgood is not ok|"
    r"mpgood error latch is active|alert \d.*active|vpd .*do not match|"
    r"vpd check.*not match|critical input interrupt.*warning", re.IGNORECASE)
INCIDENT_PAT = re.compile(
    r"error loading|invalid or missing program image|chdir\(.*\) failed|"
    r"error creating node map|kernel terminated|rts internal error|internal error|"
    r"mount failed|error receiving packet|link training failed|bad message header|"
    r"norouteto|link has been severed|error reading message prefix|\bassert\b|"
    r"not fully functional|can not get assembly|error recovery for block|bad datanode|"
    r"datastreamer exception|responseprocessor exception|error writing history|"
    r"error in contacting|failure sending status|aborting recovery|cleanup failed|"
    r"exception causing close|exception causing shutdown|unexpected exception|"
    r"got exception while serving|exception when using channel|broken pipe|"
    r"exception when following the leader|threw an exception|threw exception|"
    r"slow readprocessor|missing or invalid fields|"
    r"\bpanic\b|stopping execution|read message prefix|tlb error|data storage interrupt",
    re.IGNORECASE)
BENIGN_PAT = re.compile(
    r"machine state register|exception syndrome register|core configuration register|"
    r"data address:|\biar\b .*\bdear\b|data cache block touch|prefetch threshold|"
    r"floating pt|debug wait enable|force load/store|data store interrupt caused by|"
    r"program interrupt:.*\.\.\.?\d\s*$|critical input interrupts|"
    r"cannot open channel to .* election address|interrupting sendworker|"
    r"send worker leaving|goodbye|end of stream|connection broken for id|"
    r"zxid.*not first|first is 0x0|got zxid|will retry|will not have old|"
    r"could not parse the old|could not delete|detected and corrected|tries=0|"
    r"prepareforservice|service action|nodeexists|address change detected|"
    r"connection request from old client|interrupted while waiting|"
    r"node card status: no alerts are active", re.IGNORECASE)

def expert_label(raw: str) -> int:
    m = re.match(r"^\d{6}\s+\d{6}\s+\d+\s+\w+\s+(.+)$", raw)
    msg = m.group(1) if m else raw
    if STRONG_PAT.search(msg): return 1
    if BENIGN_PAT.search(msg): return 0
    if INCIDENT_PAT.search(msg): return 1
    return 0



if __name__ == "__main__":
    # самопроверка: воспроизводит ручную seed-разметку 1:1
    import csv, pathlib
    seed = pathlib.Path(__file__).resolve().parents[2] / "data" / "expert_labels_seed.csv"
    if seed.exists():
        rows = list(csv.DictReader(seed.open(encoding="utf-8")))
        ok = sum(1 for r in rows if expert_label(r["raw_line"]) == int(r["label"]))
        print(f"Воспроизведение seed-разметки: {ok}/{len(rows)}")
