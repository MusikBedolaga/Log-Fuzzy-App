from __future__ import annotations

import logging

import httpx

from app.recommend.config import EMBED_MODEL, LLM_MODEL, OLLAMA_BASE_URL

logger = logging.getLogger(__name__)

_TIMEOUT_EMBED = httpx.Timeout(connect=5.0, read=60.0, write=10.0, pool=5.0)
_TIMEOUT_LLM = httpx.Timeout(connect=5.0, read=300.0, write=10.0, pool=5.0)


def get_embedding(text: str) -> list[float]:
    with httpx.Client(timeout=_TIMEOUT_EMBED) as client:
        resp = client.post(
            f"{OLLAMA_BASE_URL}/api/embeddings",
            json={"model": EMBED_MODEL, "prompt": text},
        )
        resp.raise_for_status()
        data = resp.json()
        if "embedding" not in data:
            raise ValueError(f"Ollama не вернул embedding. Ответ: {data}")
        return data["embedding"]


def get_advice(current_log: dict, similar_logs: list[dict]) -> str:
    similar_text = ""
    for i, s in enumerate(similar_logs[:3], 1):
        sim = float(s.get("similarity") or 0)
        similar_text += (
            f"\n{i}. [{s.get('level', '?')}] {s.get('component', '?')} — "
            f"{s.get('message', '')} (схожесть {sim:.0%})"
        )

    prompt = (
        "Ты — эксперт по системному мониторингу и эксплуатации серверов. "
        "Проанализируй инцидент из лога и дай практический совет на русском языке.\n\n"
        "== ТЕКУЩИЙ ИНЦИДЕНТ ==\n"
        f"Уровень: {current_log.get('level') or 'неизвестно'}\n"
        f"Компонент: {current_log.get('component') or 'неизвестно'}\n"
        f"Тип события: {current_log.get('event_type') or 'неизвестно'}\n"
        f"Сообщение: {current_log.get('message') or current_log.get('raw_text') or ''}\n"
        f"Criticality: {float(current_log.get('criticality') or 0):.3f}\n\n"
        f"== ПОХОЖИЕ ИНЦИДЕНТЫ ИЗ БАЗЫ =={similar_text or ' нет данных'}\n\n"
        "Дай структурированный ответ строго в формате:\n\n"
        "**Что произошло**\n"
        "Одно предложение.\n\n"
        "**Вероятные причины**\n"
        "- причина 1\n"
        "- причина 2\n\n"
        "**Первые шаги**\n"
        "- шаг 1\n"
        "- шаг 2\n"
        "- шаг 3\n\n"
        "**Профилактика**\n"
        "- рекомендация 1\n\n"
        "Будь конкретным и лаконичным. Отвечай только на русском языке."
    )

    with httpx.Client(timeout=_TIMEOUT_LLM) as client:
        resp = client.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json={"model": LLM_MODEL, "prompt": prompt, "stream": False},
        )
        resp.raise_for_status()
        data = resp.json()
        if "response" not in data:
            raise ValueError(f"Ollama не вернул response. Ответ: {data}")
        return data["response"]


def is_ollama_reachable() -> bool:
    try:
        with httpx.Client(timeout=httpx.Timeout(3.0)) as client:
            client.get(f"{OLLAMA_BASE_URL}/api/tags")
            return True
    except Exception:
        return False
