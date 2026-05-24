from __future__ import annotations

import os

POSTGRES_DSN: str = os.getenv(
    "LOGFUZZY_PG_DSN",
    "postgresql://logfuzzy:logfuzzy@localhost:5432/logfuzzy",
)
OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
EMBED_MODEL: str = os.getenv("EMBED_MODEL", "nomic-embed-text")
EMBED_DIM: int = int(os.getenv("EMBED_DIM", "768"))
LLM_MODEL: str = os.getenv("LLM_MODEL", "llama3.2")
