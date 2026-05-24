import { useEffect, useMemo, useState } from "react";

const DEFAULT_API_BASE = "http://127.0.0.1:8000";
const ANALYSIS_PAGE_SIZE = 100;
const DB_PAGE_SIZE = 50;

function formatBytes(bytes) {
  if (!Number.isFinite(bytes)) return "0 B";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function score(value) {
  const number = Number(value || 0);
  return number.toFixed(3);
}

function rowTone(row) {
  if (row.level === "FATAL" || row.level === "ERROR" || Number(row.criticality) >= 0.7) return "critical";
  if (row.level === "WARN" || Number(row.criticality) >= 0.45) return "warning";
  return "normal";
}

function StatCard({ label, value, hint, tone = "neutral" }) {
  return (
    <div className={`stat-card ${tone}`}>
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      {hint ? <div className="stat-hint">{hint}</div> : null}
    </div>
  );
}

function Badge({ children, tone = "neutral" }) {
  return <span className={`badge ${tone}`}>{children}</span>;
}

function ScoreBar({ value }) {
  const safeValue = Math.max(0, Math.min(1, Number(value || 0)));
  // hue from green (120) to red (0)
  const hue = Math.round((1 - safeValue) * 120);
  const color = `hsl(${hue} 70% 45%)`;
  return (
    <div className="score-bar" aria-label={`criticality ${safeValue}`}>
      <span style={{ width: `${safeValue * 100}%`, background: color }} />
    </div>
  );
}

function Histogram({ bins }) {
  const max = Math.max(...(bins || []).map((bin) => bin.count), 1);
  return (
    <div className="histogram">
      {(bins || []).map((bin) => (
        <div key={bin.label} className="histogram-bin">
          <div className="histogram-count">{bin.count}</div>
          <div className="histogram-bar-wrap">
            <div
              className="histogram-bar"
              style={{ height: `${(bin.count / max) * 100}%` }}
              title={`${bin.label}: ${bin.count}`}
            />
          </div>
          <div className="histogram-label">{bin.label}</div>
        </div>
      ))}
    </div>
  );
}

function DonutChart({ data = {}, size = 160, thickness = 20, colors = [] }) {
  const entries = Object.entries(data || {}).filter(([, v]) => Number(v) > 0);
  const total = entries.reduce((s, [, v]) => s + Number(v), 0) || 0;
  const radius = size / 2 - thickness / 2;
  const circumference = 2 * Math.PI * radius;
  let cumulative = 0;

  return (
    <div className="donut-wrap">
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="donut-svg">
        <g transform={`translate(${size / 2}, ${size / 2}) rotate(-90)`}>
          {entries.map(([label, value], i) => {
            const v = Number(value);
            const fraction = total ? v / total : 0;
            const dash = fraction * circumference;
            const offset = cumulative * circumference;
            const stroke = colors[i] || (i === 0 ? '#ef4444' : i === 1 ? '#f59e0b' : '#2563eb');
            cumulative += fraction;
            return (
              <circle
                key={label}
                r={radius}
                cx={0}
                cy={0}
                fill="none"
                stroke={stroke}
                strokeWidth={thickness}
                strokeDasharray={`${dash} ${circumference}`}
                strokeDashoffset={-offset}
                style={{ transition: 'stroke-dasharray 0.5s, stroke-dashoffset 0.5s' }}
              />
            );
          })}
        </g>
        <circle cx={size / 2} cy={size / 2} r={size / 2 - thickness - 4} fill="transparent" />
      </svg>
      <div className="donut-center">{total}</div>
      <div className="donut-legend">
        {entries.map(([label, value], i) => (
          <div key={label} className="donut-legend-row">
            <span className="dot" style={{ background: colors[i] || (i === 0 ? '#ef4444' : i === 1 ? '#f59e0b' : '#2563eb') }} />
            <span className="label">{label}</span>
            <strong className="count">{value}</strong>
          </div>
        ))}
      </div>
    </div>
  );
}

function EmptyState({ title }) {
  return <div className="empty-state">{title}</div>;
}

export default function App() {
  const [apiBase, setApiBase] = useState(DEFAULT_API_BASE);
  const [activeView, setActiveView] = useState("database");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const [recStatus, setRecStatus] = useState({ ollama_reachable: false, pg_indexed: -1, embed_model: "", llm_model: "" });
  const [indexing, setIndexing] = useState(false);

  const [datasets, setDatasets] = useState([]);
  const [loadingDatasets, setLoadingDatasets] = useState(false);

  const [dbOverview, setDbOverview] = useState({ total_logs: 0, total_sources: 0, critical_logs: 0 });
  const [sources, setSources] = useState([]);
  const [dbOptions, setDbOptions] = useState({ levels: [], event_types: [], sources: [] });
  const [dbStats, setDbStats] = useState(null);
  const [dbRows, setDbRows] = useState({ rows: [], total: 0, page: 1, page_size: DB_PAGE_SIZE });
  const [dbFilters, setDbFilters] = useState({
    search: "",
    source_name: "",
    level: "",
    event_type: "",
    component: "",
    min_criticality: "",
    critical_only: false,
    sort_by: "criticality",
    sort_order: "desc",
  });
  const [selectedLog, setSelectedLog] = useState(null);
  const [logForm, setLogForm] = useState({ id: null, source_name: "manual", raw_text: "" });
  const [loadingDb, setLoadingDb] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [savingLog, setSavingLog] = useState(false);

  const [sourceType, setSourceType] = useState("dataset");
  const [selectedDataset, setSelectedDataset] = useState("");
  const [manualText, setManualText] = useState("");
  const [uploadFile, setUploadFile] = useState(null);
  const [analysis, setAnalysis] = useState(null);
  const [analysisRows, setAnalysisRows] = useState({ rows: [], total: 0, page: 1, page_size: ANALYSIS_PAGE_SIZE });
  const [analysisFilters, setAnalysisFilters] = useState({
    level: "",
    event_type: "",
    component: "",
    search: "",
    sort_by: "criticality",
    sort_order: "desc",
  });
  const [analyzing, setAnalyzing] = useState(false);
  const [loadingAnalysisRows, setLoadingAnalysisRows] = useState(false);

  const cleanApiBase = useMemo(() => apiBase.replace(/\/+$/, ""), [apiBase]);

  

  useEffect(() => {
    void refreshInitialData();
    void fetchRecStatus();
  }, []);

  async function fetchRecStatus() {
    try {
      const data = await fetch(`${cleanApiBase}/recommend/status`).then((r) => r.json());
      setRecStatus(data);
    } catch {
      // ollama/postgres могут быть недоступны — это нормально
    }
  }

  async function handleIndexAll() {
    setIndexing(true);
    setNotice("");
    setError("");
    try {
      const resp = await fetch(`${cleanApiBase}/recommend/index-all?limit=500`, { method: "POST" });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) throw new Error(data.detail || `HTTP ${resp.status}`);
      setNotice(data.message || "Индексация запущена в фоне");
      setTimeout(() => void fetchRecStatus(), 3000);
    } catch (err) {
      setError(err.message);
    } finally {
      setIndexing(false);
    }
  }

  async function apiRequest(path, options = {}) {
    const response = await fetch(`${cleanApiBase}${path}`, options);
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload.detail || `HTTP ${response.status}`);
    }
    return payload;
  }

  async function refreshInitialData() {
    setError("");
    await Promise.allSettled([fetchDatasets(), refreshDatabase()]);
  }

  async function fetchDatasets() {
    setLoadingDatasets(true);
    try {
      const data = await apiRequest("/datasets");
      setDatasets(data.datasets ?? []);
      if (!selectedDataset && data.datasets?.length) {
        setSelectedDataset(data.datasets[0].name);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoadingDatasets(false);
    }
  }

  function buildLogParams(page, filters) {
    const params = new URLSearchParams({
      page: String(page),
      page_size: String(DB_PAGE_SIZE),
      sort_by: filters.sort_by,
      sort_order: filters.sort_order,
    });
    if (filters.search) params.set("search", filters.search);
    if (filters.source_name) params.set("source_name", filters.source_name);
    if (filters.level) params.set("level", filters.level);
    if (filters.event_type) params.set("event_type", filters.event_type);
    if (filters.component) params.set("component", filters.component);
    if (filters.min_criticality !== "") params.set("min_criticality", filters.min_criticality);
    if (filters.critical_only) params.set("critical_only", "true");
    return params;
  }

  function buildStatsParams(filters) {
    const params = new URLSearchParams({ limit: "10" });
    if (filters.search) params.set("search", filters.search);
    if (filters.source_name) params.set("source_name", filters.source_name);
    if (filters.level) params.set("level", filters.level);
    if (filters.event_type) params.set("event_type", filters.event_type);
    if (filters.component) params.set("component", filters.component);
    if (filters.min_criticality !== "") params.set("min_criticality", filters.min_criticality);
    if (filters.critical_only) params.set("critical_only", "true");
    return params;
  }

  async function refreshDatabase(nextFilters = dbFilters, page = 1) {
    setLoadingDb(true);
    setError("");
    try {
      const [health, sourcesPayload, optionsPayload, statsPayload, rowsPayload] = await Promise.all([
        apiRequest("/health"),
        apiRequest("/logs/sources"),
        apiRequest("/logs/filters"),
        apiRequest(`/logs/stats?${buildStatsParams(nextFilters).toString()}`),
        apiRequest(`/logs?${buildLogParams(page, nextFilters).toString()}`),
      ]);
      setDbOverview(health.database ?? { total_logs: 0, total_sources: 0, critical_logs: 0 });
      setSources(sourcesPayload.sources ?? []);
      setDbOptions(optionsPayload);
      setDbStats(statsPayload);
      setDbRows(rowsPayload);
      if (selectedLog && !rowsPayload.rows.some((row) => row.id === selectedLog.id)) {
        setSelectedLog(null);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoadingDb(false);
    }
  }

  function updateDbFilter(name, value) {
    setDbFilters((current) => ({ ...current, [name]: value }));
  }

  async function applyDbFilters() {
    await refreshDatabase(dbFilters, 1);
  }

  async function syncData(force = false) {
    setSyncing(true);
    setNotice("");
    setError("");
    try {
      const payload = await apiRequest("/logs/import-data", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ force }),
      });
      setNotice(
        `Импортировано: ${payload.imported_count}, пропущено: ${payload.skipped_count}, ошибок: ${payload.error_count}`
      );
      await refreshDatabase(dbFilters, 1);
    } catch (err) {
      setError(err.message);
    } finally {
      setSyncing(false);
    }
  }

  function selectLog(row) {
    setSelectedLog(row);
    setLogForm({
      id: row.id,
      source_name: row.source_name || "manual",
      raw_text: row.raw_text || row.message || "",
    });
  }

  function startNewLog() {
    setSelectedLog(null);
    setLogForm({ id: null, source_name: "manual", raw_text: "" });
  }

  async function saveLog(event) {
    event.preventDefault();
    setSavingLog(true);
    setNotice("");
    setError("");
    try {
      const payload = {
        source_name: logForm.source_name || "manual",
        raw_text: logForm.raw_text,
      };
      const saved = logForm.id
        ? await apiRequest(`/logs/${logForm.id}`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          })
        : await apiRequest("/logs", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          });
      setNotice(logForm.id ? "Лог обновлен" : "Лог создан");
      setSelectedLog(saved);
      setLogForm({ id: saved.id, source_name: saved.source_name || "manual", raw_text: saved.raw_text || "" });
      await refreshDatabase(dbFilters, dbRows.page);
    } catch (err) {
      setError(err.message);
    } finally {
      setSavingLog(false);
    }
  }

  async function deleteCurrentLog() {
    if (!logForm.id) return;
    const confirmed = window.confirm("Удалить выбранный лог из базы данных?");
    if (!confirmed) return;

    setSavingLog(true);
    setNotice("");
    setError("");
    try {
      await apiRequest(`/logs/${logForm.id}`, { method: "DELETE" });
      setNotice("Лог удален");
      startNewLog();
      await refreshDatabase(dbFilters, dbRows.page);
    } catch (err) {
      setError(err.message);
    } finally {
      setSavingLog(false);
    }
  }

  async function analyzeSource() {
    setAnalyzing(true);
    setError("");
    setNotice("");
    try {
      let response;

      if (sourceType === "dataset") {
        response = await apiRequest("/analyze/dataset", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ dataset_name: selectedDataset }),
        });
      } else if (sourceType === "text") {
        response = await apiRequest("/analyze/text", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text: manualText, source_name: "manual_input.log" }),
        });
      } else {
        if (!uploadFile) {
          throw new Error("Выбери файл для загрузки");
        }
        const formData = new FormData();
        formData.append("file", uploadFile);
        response = await apiRequest("/analyze/upload", {
          method: "POST",
          body: formData,
        });
      }

      setAnalysis(response);
      const resetFilters = {
        level: "",
        event_type: "",
        component: "",
        search: "",
        sort_by: "criticality",
        sort_order: "desc",
      };
      setAnalysisFilters(resetFilters);
      await fetchAnalysisRows(response.analysis_id, 1, resetFilters);
    } catch (err) {
      setError(err.message);
    } finally {
      setAnalyzing(false);
    }
  }

  async function fetchAnalysisRows(analysisId, page = 1, nextFilters = analysisFilters) {
    if (!analysisId) return;
    setLoadingAnalysisRows(true);
    setError("");
    try {
      const params = new URLSearchParams({
        page: String(page),
        page_size: String(ANALYSIS_PAGE_SIZE),
        sort_by: nextFilters.sort_by,
        sort_order: nextFilters.sort_order,
      });
      if (nextFilters.level) params.set("level", nextFilters.level);
      if (nextFilters.event_type) params.set("event_type", nextFilters.event_type);
      if (nextFilters.component) params.set("component", nextFilters.component);
      if (nextFilters.search) params.set("search", nextFilters.search);

      const payload = await apiRequest(`/analyses/${analysisId}/rows?${params.toString()}`);
      setAnalysisRows(payload);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoadingAnalysisRows(false);
    }
  }

  function updateAnalysisFilter(name, value) {
    setAnalysisFilters((current) => ({ ...current, [name]: value }));
  }

  const dbPageCount = useMemo(() => Math.max(1, Math.ceil((dbRows.total || 0) / DB_PAGE_SIZE)), [dbRows.total]);
  const analysisPageCount = useMemo(
    () => Math.max(1, Math.ceil((analysisRows.total || 0) / ANALYSIS_PAGE_SIZE)),
    [analysisRows.total]
  );
  const summary = analysis?.summary;

  return (
    <div className="app-shell">
      <header className="topbar">
        <div>
          <div className="brand">LogFuzzy</div>
          <div className="brand-subtitle">База логов, поиск и fuzzy-анализ критичности</div>
        </div>
        <nav className="tabs">
          <button className={activeView === "database" ? "active" : ""} onClick={() => setActiveView("database")}>
            Логи в БД
          </button>
          <button className={activeView === "analysis" ? "active" : ""} onClick={() => setActiveView("analysis")}>
            Анализ файла
          </button>
        </nav>
      </header>

      <div className="workspace">
        <aside className="sidebar">
          <section className="panel">
            <label className="label">API URL</label>
            <input value={apiBase} onChange={(event) => setApiBase(event.target.value)} placeholder={DEFAULT_API_BASE} />
            <button className="secondary full" onClick={() => void refreshInitialData()} disabled={loadingDb || loadingDatasets}>
              Обновить подключение
            </button>
          </section>

          <section className="panel">
            <div className="panel-title">База данных</div>
            <div className="mini-grid">
              <StatCard label="Логов" value={dbOverview.total_logs} />
              <StatCard label="Источников" value={dbOverview.total_sources} />
              <StatCard label="Критичных" value={dbOverview.critical_logs} tone="danger" />
            </div>
            <div className="button-row">
              <button className="primary" onClick={() => void syncData(false)} disabled={syncing}>
                {syncing ? "Синхронизация..." : "Импорт data"}
              </button>
              <button className="secondary" onClick={() => void syncData(true)} disabled={syncing}>
                Форсировать
              </button>
            </div>
          </section>

          {activeView === "analysis" ? (
            <section className="panel">
              <div className="panel-title">Источник анализа</div>
              <div className="segmented">
                <button className={sourceType === "dataset" ? "active" : ""} onClick={() => setSourceType("dataset")}>
                  Датасет
                </button>
                <button className={sourceType === "upload" ? "active" : ""} onClick={() => setSourceType("upload")}>
                  Файл
                </button>
                <button className={sourceType === "text" ? "active" : ""} onClick={() => setSourceType("text")}>
                  Текст
                </button>
              </div>

              {sourceType === "dataset" ? (
                <>
                  <label className="label">Файл из data</label>
                  <select value={selectedDataset} onChange={(event) => setSelectedDataset(event.target.value)}>
                    {datasets.map((dataset) => (
                      <option key={dataset.name} value={dataset.name}>
                        {dataset.name} ({formatBytes(dataset.size_bytes)})
                      </option>
                    ))}
                  </select>
                </>
              ) : null}

              {sourceType === "upload" ? (
                <>
                  <label className="label">Локальный файл</label>
                  <input type="file" accept=".log,.txt" onChange={(event) => setUploadFile(event.target.files?.[0] ?? null)} />
                </>
              ) : null}

              {sourceType === "text" ? (
                <>
                  <label className="label">Текст логов</label>
                  <textarea rows={8} value={manualText} onChange={(event) => setManualText(event.target.value)} />
                </>
              ) : null}

              <button className="primary full" onClick={() => void analyzeSource()} disabled={analyzing}>
                {analyzing ? "Анализ..." : "Запустить анализ"}
              </button>
            </section>
          ) : null}

          <section className="panel">
            <div className="panel-title">AI-рекомендации</div>
            <div className="mini-grid">
              <StatCard
                label="В индексе"
                value={recStatus.pg_indexed >= 0 ? recStatus.pg_indexed : "—"}
                hint={recStatus.pg_indexed < 0 ? "нет связи" : undefined}
              />
              <StatCard
                label="Ollama"
                value={recStatus.ollama_reachable ? "online" : "offline"}
                tone={recStatus.ollama_reachable ? "neutral" : "danger"}
              />
            </div>
            {recStatus.embed_model ? (
              <div style={{ fontSize: "0.76rem", color: "var(--muted)", margin: "0.4rem 0 0.1rem" }}>
                embed: {recStatus.embed_model} · llm: {recStatus.llm_model}
              </div>
            ) : null}
            <button className="secondary full" onClick={() => void handleIndexAll()} disabled={indexing}>
              {indexing ? "Индексация..." : "Индексировать (≤500 логов)"}
            </button>
            <button className="secondary full" style={{ marginTop: "0.35rem" }} onClick={() => void fetchRecStatus()} disabled={indexing}>
              Обновить статус
            </button>
          </section>

          {sources.length ? (
            <section className="panel">
              <div className="panel-title">Импортированные источники</div>
              <div className="source-list">
                {sources.slice(0, 8).map((source) => (
                  <div key={source.id} className="source-item">
                    <span>{source.name}</span>
                    <strong>{source.db_log_count}</strong>
                  </div>
                ))}
              </div>
            </section>
          ) : null}

          {notice ? <div className="notice-box">{notice}</div> : null}
          {error ? <div className="error-box">{error}</div> : null}
        </aside>

        <main className="content">
          {activeView === "database" ? (
            <DatabaseView
              rowsState={dbRows}
              pageCount={dbPageCount}
              filters={dbFilters}
              options={dbOptions}
              stats={dbStats}
              selectedLog={selectedLog}
              logForm={logForm}
              loading={loadingDb}
              saving={savingLog}
              updateFilter={updateDbFilter}
              applyFilters={applyDbFilters}
              refreshPage={(page) => refreshDatabase(dbFilters, page)}
              selectLog={selectLog}
              startNewLog={startNewLog}
              setLogForm={setLogForm}
              saveLog={saveLog}
              deleteCurrentLog={deleteCurrentLog}
              apiBase={cleanApiBase}
            />
          ) : (
            <AnalysisView
              summary={summary}
              analysis={analysis}
              rowsState={analysisRows}
              pageCount={analysisPageCount}
              filters={analysisFilters}
              loadingRows={loadingAnalysisRows}
              updateFilter={updateAnalysisFilter}
              applyFilters={() => analysis && fetchAnalysisRows(analysis.analysis_id, 1, analysisFilters)}
              refreshPage={(page) => analysis && fetchAnalysisRows(analysis.analysis_id, page)}
              apiBase={cleanApiBase}
            />
          )}
        </main>
      </div>
    </div>
  );
}

function DatabaseView({
  rowsState,
  pageCount,
  filters,
  options,
  stats,
  selectedLog,
  logForm,
  loading,
  saving,
  updateFilter,
  applyFilters,
  refreshPage,
  selectLog,
  startNewLog,
  setLogForm,
  saveLog,
  deleteCurrentLog,
  apiBase,
}) {
  const [rec, setRec] = useState({ mode: null, loading: false, similar: [], advice: "", error: "" });

  useEffect(() => {
    setRec({ mode: null, loading: false, similar: [], advice: "", error: "" });
  }, [selectedLog?.id]);

  async function handleSimilar() {
    if (!selectedLog) return;
    setRec((s) => ({ ...s, mode: "similar", loading: true, error: "", similar: [], advice: "" }));
    try {
      const resp = await fetch(`${apiBase}/recommend/similar`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ log_id: selectedLog.id, limit: 5 }),
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) throw new Error(data.detail || `HTTP ${resp.status}`);
      setRec((s) => ({ ...s, loading: false, similar: data.similar || [] }));
    } catch (err) {
      setRec((s) => ({ ...s, loading: false, error: err.message }));
    }
  }

  async function handleAdvice() {
    if (!selectedLog) return;
    setRec((s) => ({ ...s, mode: "advice", loading: true, error: "", similar: [], advice: "" }));
    try {
      const resp = await fetch(`${apiBase}/recommend/advice`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ log_id: selectedLog.id }),
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) throw new Error(data.detail || `HTTP ${resp.status}`);
      setRec((s) => ({ ...s, loading: false, advice: data.advice || "", similar: data.similar || [] }));
    } catch (err) {
      setRec((s) => ({ ...s, loading: false, error: err.message }));
    }
  }

  const summary = stats?.summary ?? {};
  const levelsArray = stats?.levels ?? [];
  const eventTypesArray = stats?.event_types ?? [];
  const levelsMap = levelsArray.reduce((acc, cur) => {
    try {
      const key = cur.level ?? cur["level"] ?? String(cur[0] ?? "");
      const val = Number(cur.count ?? cur["count"] ?? cur[1] ?? 0) || 0;
      acc[key] = val;
    } catch (e) {
      // ignore
    }
    return acc;
  }, {});
  const eventBins = (eventTypesArray || []).slice(0, 12).map((et) => ({ label: et.event_type ?? et["event_type"], count: et.count ?? et["count"] }));

  return (
    <>
      <section className="analytics-grid two">
        <div className="panel">
          <div className="panel-title">Топ событий по числу (DB)</div>
          {eventBins && eventBins.length ? <Histogram bins={eventBins} /> : <EmptyState title="Нет данных" />}
        </div>
        <div className="panel">
          <div className="panel-title">Уровни логов</div>
          {levelsArray && levelsArray.length ? (
            <DonutChart data={levelsMap} size={160} thickness={18} colors={["#ef4444", "#f59e0b", "#2563eb", "#60a5fa"]} />
          ) : (
            <EmptyState title="Нет данных" />
          )}
        </div>
      </section>
      <section className="summary-grid">
        <StatCard label="Найдено" value={summary.total ?? 0} />
        <StatCard label="Критичные" value={summary.critical_count ?? 0} tone="danger" />
        <StatCard label="WARN" value={summary.warn_count ?? 0} tone="warning" />
        <StatCard label="ERROR/FATAL" value={summary.error_count ?? 0} tone="danger" />
        <StatCard label="Средняя criticality" value={score(summary.avg_criticality)} hint={`max ${score(summary.max_criticality)}`} />
      </section>

      <section className="panel">
        <div className="panel-title">Поиск и фильтры</div>
        <div className="filters">
          <input value={filters.search} onChange={(event) => updateFilter("search", event.target.value)} placeholder="Поиск по сообщению, компоненту, сигнатуре" />
          <select value={filters.source_name} onChange={(event) => updateFilter("source_name", event.target.value)}>
            <option value="">Все источники</option>
            {(options.sources || []).map((source) => (
              <option key={source} value={source}>
                {source}
              </option>
            ))}
          </select>
          <select value={filters.level} onChange={(event) => updateFilter("level", event.target.value)}>
            <option value="">Все уровни</option>
            {(options.levels || []).map((level) => (
              <option key={level} value={level}>
                {level}
              </option>
            ))}
          </select>
          <select value={filters.event_type} onChange={(event) => updateFilter("event_type", event.target.value)}>
            <option value="">Все события</option>
            {(options.event_types || []).map((eventType) => (
              <option key={eventType} value={eventType}>
                {eventType}
              </option>
            ))}
          </select>
          <input value={filters.component} onChange={(event) => updateFilter("component", event.target.value)} placeholder="Component" />
          <input
            type="number"
            min="0"
            max="1"
            step="0.05"
            value={filters.min_criticality}
            onChange={(event) => updateFilter("min_criticality", event.target.value)}
            placeholder="Min criticality"
          />
          <select value={filters.sort_by} onChange={(event) => updateFilter("sort_by", event.target.value)}>
            <option value="criticality">criticality</option>
            <option value="id">id</option>
            <option value="ts">ts</option>
            <option value="level">level</option>
            <option value="event_type">event_type</option>
            <option value="component">component</option>
            <option value="source_name">source_name</option>
          </select>
          <select value={filters.sort_order} onChange={(event) => updateFilter("sort_order", event.target.value)}>
            <option value="desc">desc</option>
            <option value="asc">asc</option>
          </select>
          <label className="check-row">
            <input type="checkbox" checked={filters.critical_only} onChange={(event) => updateFilter("critical_only", event.target.checked)} />
            Только критичные
          </label>
          <button className="primary" onClick={() => void applyFilters()} disabled={loading}>
            Применить
          </button>
        </div>
      </section>

      <section className="db-grid">
        <div className="panel table-panel">
          <div className="table-header">
            <div>
              <div className="panel-title">Логи</div>
              <div className="table-meta">
                {loading ? "Загрузка..." : `Показано ${rowsState.rows.length} из ${rowsState.total}`}
              </div>
            </div>
            <div className="pagination">
              <button className="secondary compact" onClick={() => void refreshPage(rowsState.page - 1)} disabled={rowsState.page <= 1 || loading}>
                Назад
              </button>
              <span>
                {rowsState.page} / {pageCount}
              </span>
              <button className="secondary compact" onClick={() => void refreshPage(rowsState.page + 1)} disabled={rowsState.page >= pageCount || loading}>
                Вперед
              </button>
            </div>
          </div>

          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Источник</th>
                  <th>ts</th>
                  <th>level</th>
                  <th>component</th>
                  <th>event</th>
                  <th>criticality</th>
                  <th>message</th>
                </tr>
              </thead>
              <tbody>
                {rowsState.rows.map((row) => (
                  <tr
                    key={row.id}
                    className={`${rowTone(row)} ${selectedLog?.id === row.id ? "selected" : ""}`}
                    onClick={() => selectLog(row)}
                  >
                    <td>{row.id}</td>
                    <td className="mono">{row.source_name}</td>
                    <td>{row.ts || "-"}</td>
                    <td>
                      <Badge tone={rowTone(row)}>{row.level || "UNKNOWN"}</Badge>
                    </td>
                    <td className="mono clipped">{row.component || "-"}</td>
                    <td className="mono">{row.event_type || "-"}</td>
                    <td>
                      <div className="score-cell">
                        <span>{score(row.criticality)}</span>
                        <ScoreBar value={row.criticality} />
                      </div>
                    </td>
                    <td className="message-cell">{row.message || row.raw_text}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <aside className="panel detail-panel">
          <div className="detail-header">
            <div className="panel-title">{logForm.id ? `Лог #${logForm.id}` : "Новый лог"}</div>
            <button className="secondary compact" onClick={startNewLog}>
              Новый
            </button>
          </div>

          <form onSubmit={saveLog} className="log-form">
            <label className="label">Источник</label>
            <input value={logForm.source_name} onChange={(event) => setLogForm((current) => ({ ...current, source_name: event.target.value }))} />
            <label className="label">Raw text</label>
            <textarea
              rows={7}
              value={logForm.raw_text}
              onChange={(event) => setLogForm((current) => ({ ...current, raw_text: event.target.value }))}
            />
            <div className="button-row">
              <button className="primary" type="submit" disabled={saving}>
                {saving ? "Сохранение..." : logForm.id ? "Обновить" : "Создать"}
              </button>
              <button className="danger" type="button" onClick={() => void deleteCurrentLog()} disabled={!logForm.id || saving}>
                Удалить
              </button>
            </div>
          </form>

          {selectedLog ? (
            <div className="details">
              <div className="panel-title nested">Детали</div>
              <div className="detail-line">
                <span>Сигнатура</span>
                <strong className="mono">{selectedLog.signature || "-"}</strong>
              </div>
              <div className="detail-line">
                <span>Строка</span>
                <strong>{selectedLog.line_number || "-"}</strong>
              </div>
              <div className="detail-line">
                <span>Parse OK</span>
                <strong>{selectedLog.parse_ok ? "yes" : "no"}</strong>
              </div>
              <div className="factor-grid">
                <StatCard label="level" value={score(selectedLog.x_level)} />
                <StatCard label="kb" value={score(selectedLog.x_kb_base)} />
                <StatCard label="lex" value={score(selectedLog.x_lex)} />
                <StatCard label="ctx" value={score(selectedLog.x_ctx)} />
                <StatCard label="param" value={score(selectedLog.x_param)} />
              </div>

              <div className="rec-section">
                <div className="panel-title nested">AI-рекомендации</div>
                <div className="button-row">
                  <button
                    className="secondary"
                    type="button"
                    onClick={() => void handleSimilar()}
                    disabled={rec.loading}
                  >
                    {rec.loading && rec.mode === "similar" ? "Поиск..." : "Похожие"}
                  </button>
                  <button
                    className="primary"
                    type="button"
                    onClick={() => void handleAdvice()}
                    disabled={rec.loading}
                  >
                    {rec.loading && rec.mode === "advice" ? "Анализ..." : "Совет"}
                  </button>
                </div>

                {rec.error ? <div className="error-box rec-error">{rec.error}</div> : null}

                {rec.mode === "similar" && !rec.loading && rec.similar.length === 0 && !rec.error ? (
                  <div className="empty-state" style={{ padding: "0.5rem 0", fontSize: "0.82rem" }}>
                    Нет данных — сначала нажмите «Индексировать» в сайдбаре
                  </div>
                ) : null}

                {rec.mode === "similar" && !rec.loading && rec.similar.length > 0 ? (
                  <div className="rec-similar">
                    {rec.similar.map((s) => (
                      <div key={s.log_id} className={`rec-item ${rowTone(s)}`}>
                        <div className="rec-item-header">
                          <Badge tone={rowTone(s)}>{s.level || "?"}</Badge>
                          <span className="rec-sim">{Math.round((s.similarity || 0) * 100)}%</span>
                        </div>
                        <div className="rec-item-component mono">{s.component || ""}</div>
                        <div className="rec-item-message">{s.message}</div>
                        <div className="rec-item-id muted">#{s.log_id} · crit {score(s.criticality)}</div>
                      </div>
                    ))}
                  </div>
                ) : null}

                {rec.mode === "advice" && !rec.loading && rec.advice ? (
                  <div className="rec-advice">
                    <pre>{rec.advice}</pre>
                  </div>
                ) : null}
              </div>
            </div>
          ) : null}
        </aside>
      </section>

      <section className="analytics-grid">
        <div className="panel">
          <div className="panel-title">Проблемные компоненты</div>
          <div className="rank-list">
            {(stats?.problem_components || []).map((item) => (
              <div key={item.component} className="rank-row">
                <span className="mono">{item.component}</span>
                <strong>{item.critical_count} крит.</strong>
                <small>avg {score(item.avg_criticality)}</small>
              </div>
            ))}
            {!(stats?.problem_components || []).length ? <EmptyState title="Нет данных" /> : null}
          </div>
        </div>

        <div className="panel">
          <div className="panel-title">Повторяющиеся ошибки</div>
          <div className="rank-list">
            {(stats?.repeated_errors || []).map((item) => (
              <button key={`${item.signature}-${item.component}`} className="rank-row clickable" onClick={() => updateFilter("search", item.signature)}>
                <span className="mono">{item.signature}</span>
                <strong>{item.count} раз</strong>
                <small>{item.component}</small>
              </button>
            ))}
            {!(stats?.repeated_errors || []).length ? <EmptyState title="Нет данных" /> : null}
          </div>
        </div>

        <div className="panel">
          <div className="panel-title">Критичные записи</div>
          <div className="rank-list">
            {(stats?.critical_rows || []).map((row) => (
              <button key={row.id} className="rank-row clickable" onClick={() => selectLog(row)}>
                <span>{row.message || row.raw_text}</span>
                <strong>{score(row.criticality)}</strong>
                <small>#{row.id}</small>
              </button>
            ))}
            {!(stats?.critical_rows || []).length ? <EmptyState title="Нет данных" /> : null}
          </div>
        </div>
      </section>
    </>
  );
}

function AnalysisView({ summary, analysis, rowsState, pageCount, filters, loadingRows, updateFilter, applyFilters, refreshPage, apiBase }) {
  if (!summary) {
    return <EmptyState title="Запусти анализ датасета, файла или ручного текста" />;
  }

  return (
    <>
      <section className="summary-grid">
        <StatCard label="Источник" value={summary.source_name} />
        <StatCard label="Строк" value={summary.row_count} />
        <StatCard label="Parse OK" value={`${(summary.parse_ok_rate * 100).toFixed(1)}%`} />
        <StatCard label="WARN" value={`${(summary.warn_rate * 100).toFixed(1)}%`} tone="warning" />
        <StatCard label="Средняя criticality" value={score(summary.criticality.mean)} hint={`max ${score(summary.criticality.max)}`} />
      </section>

      <section className="analytics-grid two">
        <div className="panel">
          <div className="panel-title">Распределение criticality</div>
          <Histogram bins={summary.histogram} />
        </div>
        <div className="panel">
          <div className="panel-title">Сводка</div>
          <div className="tag-list">
            {Object.entries(summary.levels).map(([level, count]) => (
              <Badge key={level} tone={level === "WARN" ? "warning" : level === "ERROR" || level === "FATAL" ? "critical" : "neutral"}>
                {level}: {count}
              </Badge>
            ))}
          </div>
          <div className="panel-title nested">События</div>
          <div className="tag-list">
            {Object.entries(summary.event_types).map(([eventType, count]) => (
              <Badge key={eventType}>{eventType}: {count}</Badge>
            ))}
          </div>
          <button className="secondary full" onClick={() => window.open(`${apiBase}/analyses/${analysis.analysis_id}/download`, "_blank")}>
            Скачать CSV
          </button>
        </div>
      </section>

      <section className="panel">
        <div className="panel-title">Фильтры</div>
        <div className="filters analysis-filters">
          <select value={filters.level} onChange={(event) => updateFilter("level", event.target.value)}>
            <option value="">Все уровни</option>
            {summary.filter_options.levels.map((level) => (
              <option key={level} value={level}>
                {level}
              </option>
            ))}
          </select>
          <select value={filters.event_type} onChange={(event) => updateFilter("event_type", event.target.value)}>
            <option value="">Все события</option>
            {summary.filter_options.event_types.map((eventType) => (
              <option key={eventType} value={eventType}>
                {eventType}
              </option>
            ))}
          </select>
          <input value={filters.component} onChange={(event) => updateFilter("component", event.target.value)} placeholder="Component" />
          <input value={filters.search} onChange={(event) => updateFilter("search", event.target.value)} placeholder="Поиск" />
          <select value={filters.sort_by} onChange={(event) => updateFilter("sort_by", event.target.value)}>
            <option value="criticality">criticality</option>
            <option value="ts">ts</option>
            <option value="level">level</option>
            <option value="event_type">event_type</option>
            <option value="component">component</option>
            <option value="row_id">row_id</option>
          </select>
          <select value={filters.sort_order} onChange={(event) => updateFilter("sort_order", event.target.value)}>
            <option value="desc">desc</option>
            <option value="asc">asc</option>
          </select>
          <button className="primary" onClick={() => void applyFilters()} disabled={loadingRows}>
            Применить
          </button>
        </div>
      </section>

      <section className="panel">
        <div className="table-header">
          <div>
            <div className="panel-title">Результаты</div>
            <div className="table-meta">
              {loadingRows ? "Загрузка..." : `Показано ${rowsState.rows.length} из ${rowsState.total}`}
            </div>
          </div>
          <div className="pagination">
            <button className="secondary compact" onClick={() => void refreshPage(rowsState.page - 1)} disabled={rowsState.page <= 1 || loadingRows}>
              Назад
            </button>
            <span>
              {rowsState.page} / {pageCount}
            </span>
            <button className="secondary compact" onClick={() => void refreshPage(rowsState.page + 1)} disabled={rowsState.page >= pageCount || loadingRows}>
              Вперед
            </button>
          </div>
        </div>

        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>#</th>
                <th>ts</th>
                <th>level</th>
                <th>component</th>
                <th>event</th>
                <th>criticality</th>
                <th>message</th>
              </tr>
            </thead>
            <tbody>
              {rowsState.rows.map((row) => (
                <tr key={row.row_id} className={rowTone(row)}>
                  <td>{row.row_id}</td>
                  <td>{row.ts || "-"}</td>
                  <td>
                    <Badge tone={rowTone(row)}>{row.level || "UNKNOWN"}</Badge>
                  </td>
                  <td className="mono clipped">{row.component || "-"}</td>
                  <td className="mono">{row.event_type || "-"}</td>
                  <td>{score(row.criticality)}</td>
                  <td className="message-cell">{row.message}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}
