CREATE TABLE IF NOT EXISTS log_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    path TEXT UNIQUE,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    modified_at TEXT,
    imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    line_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER REFERENCES log_sources(id) ON DELETE SET NULL,
    source_name TEXT NOT NULL DEFAULT 'manual',
    line_number INTEGER,
    raw_text TEXT NOT NULL,
    date TEXT,
    time TEXT,
    pid INTEGER,
    level TEXT,
    component TEXT,
    message TEXT NOT NULL DEFAULT '',
    parse_ok INTEGER NOT NULL DEFAULT 0,
    ts TEXT,
    block_id TEXT,
    size INTEGER,
    src_ip TEXT,
    dest_ip TEXT,
    any_ip TEXT,
    event_type TEXT NOT NULL DEFAULT 'other',
    signature TEXT NOT NULL DEFAULT '',
    criticality REAL NOT NULL DEFAULT 0,
    x_level REAL NOT NULL DEFAULT 0,
    x_kb_base REAL NOT NULL DEFAULT 0,
    x_lex REAL NOT NULL DEFAULT 0,
    x_ctx REAL NOT NULL DEFAULT 0,
    x_param REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_logs_source ON logs(source_id, line_number);
CREATE INDEX IF NOT EXISTS idx_logs_source_name ON logs(source_name);
CREATE INDEX IF NOT EXISTS idx_logs_level ON logs(level);
CREATE INDEX IF NOT EXISTS idx_logs_event_type ON logs(event_type);
CREATE INDEX IF NOT EXISTS idx_logs_component ON logs(component);
CREATE INDEX IF NOT EXISTS idx_logs_signature ON logs(signature);
CREATE INDEX IF NOT EXISTS idx_logs_criticality ON logs(criticality DESC);
CREATE INDEX IF NOT EXISTS idx_logs_ts ON logs(ts);
