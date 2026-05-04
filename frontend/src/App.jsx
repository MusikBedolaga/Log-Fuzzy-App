import { useEffect, useMemo, useState } from "react";

const DEFAULT_API_BASE = "http://127.0.0.1:8000";
const PAGE_SIZE = 100;

function StatCard({ label, value, hint }) {
  return (
    <div className="stat-card">
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      {hint ? <div className="stat-hint">{hint}</div> : null}
    </div>
  );
}

function Histogram({ bins }) {
  const max = Math.max(...bins.map((bin) => bin.count), 1);
  return (
    <div className="histogram">
      {bins.map((bin) => (
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

export default function App() {
  const [apiBase, setApiBase] = useState(DEFAULT_API_BASE);
  const [datasets, setDatasets] = useState([]);
  const [sourceType, setSourceType] = useState("dataset");
  const [selectedDataset, setSelectedDataset] = useState("");
  const [manualText, setManualText] = useState("");
  const [uploadFile, setUploadFile] = useState(null);
  const [analysis, setAnalysis] = useState(null);
  const [rowsState, setRowsState] = useState({ rows: [], total: 0, page: 1, page_size: PAGE_SIZE });
  const [filters, setFilters] = useState({
    level: "",
    event_type: "",
    component: "",
    search: "",
    sort_by: "criticality",
    sort_order: "desc",
  });
  const [loadingDatasets, setLoadingDatasets] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [loadingRows, setLoadingRows] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    void fetchDatasets();
  }, []);

  async function fetchDatasets() {
    setLoadingDatasets(true);
    setError("");
    try {
      const response = await fetch(`${apiBase}/datasets`);
      if (!response.ok) {
        throw new Error("Не удалось загрузить список датасетов");
      }
      const data = await response.json();
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

  async function analyzeSource() {
    setAnalyzing(true);
    setError("");
    try {
      let response;

      if (sourceType === "dataset") {
        response = await fetch(`${apiBase}/analyze/dataset`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ dataset_name: selectedDataset }),
        });
      } else if (sourceType === "text") {
        response = await fetch(`${apiBase}/analyze/text`, {
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
        response = await fetch(`${apiBase}/analyze/upload`, {
          method: "POST",
          body: formData,
        });
      }

      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload.detail || "Не удалось выполнить анализ");
      }

      const payload = await response.json();
      setAnalysis(payload);
      setFilters({
        level: "",
        event_type: "",
        component: "",
        search: "",
        sort_by: "criticality",
        sort_order: "desc",
      });
      await fetchRows(payload.analysis_id, 1, {
        level: "",
        event_type: "",
        component: "",
        search: "",
        sort_by: "criticality",
        sort_order: "desc",
      });
    } catch (err) {
      setError(err.message);
    } finally {
      setAnalyzing(false);
    }
  }

  async function fetchRows(analysisId, page = 1, nextFilters = filters) {
    if (!analysisId) {
      return;
    }
    setLoadingRows(true);
    setError("");
    try {
      const params = new URLSearchParams({
        page: String(page),
        page_size: String(PAGE_SIZE),
        sort_by: nextFilters.sort_by,
        sort_order: nextFilters.sort_order,
      });

      if (nextFilters.level) params.set("level", nextFilters.level);
      if (nextFilters.event_type) params.set("event_type", nextFilters.event_type);
      if (nextFilters.component) params.set("component", nextFilters.component);
      if (nextFilters.search) params.set("search", nextFilters.search);

      const response = await fetch(`${apiBase}/analyses/${analysisId}/rows?${params.toString()}`);
      if (!response.ok) {
        throw new Error("Не удалось загрузить таблицу");
      }
      const payload = await response.json();
      setRowsState(payload);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoadingRows(false);
    }
  }

  function updateFilter(name, value) {
    const nextFilters = { ...filters, [name]: value };
    setFilters(nextFilters);
  }

  async function applyFilters() {
    if (!analysis) return;
    await fetchRows(analysis.analysis_id, 1, filters);
  }

  const pageCount = useMemo(() => {
    return Math.max(1, Math.ceil((rowsState.total || 0) / PAGE_SIZE));
  }, [rowsState.total]);

  const summary = analysis?.summary;

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="panel">
          <h1>LogFuzzy UI</h1>
          <p className="muted">
            React-интерфейс для оценки критичности логов через FastAPI-бэкенд.
          </p>
        </div>

        <div className="panel">
          <label className="label">API Base URL</label>
          <input value={apiBase} onChange={(e) => setApiBase(e.target.value)} placeholder={DEFAULT_API_BASE} />
          <button className="secondary" onClick={() => void fetchDatasets()} disabled={loadingDatasets}>
            {loadingDatasets ? "Обновляю..." : "Проверить API и обновить датасеты"}
          </button>
        </div>

        <div className="panel">
          <div className="label">Источник логов</div>
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
              <label className="label">Доступные датасеты</label>
              <select value={selectedDataset} onChange={(e) => setSelectedDataset(e.target.value)}>
                {datasets.map((dataset) => (
                  <option key={dataset.name} value={dataset.name}>
                    {dataset.name}
                  </option>
                ))}
              </select>
            </>
          ) : null}

          {sourceType === "upload" ? (
            <>
              <label className="label">Загрузить `.log` файл</label>
              <input type="file" accept=".log,.txt" onChange={(e) => setUploadFile(e.target.files?.[0] ?? null)} />
            </>
          ) : null}

          {sourceType === "text" ? (
            <>
              <label className="label">Вставь логи вручную</label>
              <textarea
                rows={10}
                value={manualText}
                onChange={(e) => setManualText(e.target.value)}
                placeholder="Вставь несколько строк логов..."
              />
            </>
          ) : null}

          <button className="primary" onClick={() => void analyzeSource()} disabled={analyzing}>
            {analyzing ? "Анализирую..." : "Запустить анализ"}
          </button>

          {error ? <div className="error-box">{error}</div> : null}
        </div>

        {summary ? (
          <div className="panel">
            <div className="panel-title">Экспорт</div>
            <button className="secondary" onClick={() => window.open(`${apiBase}/analyses/${analysis.analysis_id}/download`, "_blank")}>
              Скачать CSV
            </button>
          </div>
        ) : null}
      </aside>

      <main className="content">
        {summary ? (
          <>
            <section className="summary-grid">
              <StatCard label="Источник" value={summary.source_name} />
              <StatCard label="Строк" value={summary.row_count} />
              <StatCard label="Parse OK" value={`${(summary.parse_ok_rate * 100).toFixed(1)}%`} />
              <StatCard label="WARN" value={`${(summary.warn_rate * 100).toFixed(1)}%`} />
              <StatCard
                label="Средняя criticality"
                value={summary.criticality.mean.toFixed(3)}
                hint={`min ${summary.criticality.min.toFixed(3)} / max ${summary.criticality.max.toFixed(3)}`}
              />
            </section>

            <section className="grid-two">
              <div className="panel">
                <div className="panel-title">Распределение criticality</div>
                <Histogram bins={summary.histogram} />
              </div>

              <div className="panel">
                <div className="panel-title">Сводка по уровням</div>
                <div className="tag-list">
                  {Object.entries(summary.levels).map(([level, count]) => (
                    <span key={level} className="tag">
                      {level}: {count}
                    </span>
                  ))}
                </div>

                <div className="panel-title nested">Топ событий</div>
                <div className="tag-list">
                  {Object.entries(summary.event_types).map(([eventType, count]) => (
                    <span key={eventType} className="tag">
                      {eventType}: {count}
                    </span>
                  ))}
                </div>
              </div>
            </section>

            <section className="panel">
              <div className="panel-title">Фильтры</div>
              <div className="filters">
                <select value={filters.level} onChange={(e) => updateFilter("level", e.target.value)}>
                  <option value="">Все уровни</option>
                  {summary.filter_options.levels.map((level) => (
                    <option key={level} value={level}>
                      {level}
                    </option>
                  ))}
                </select>

                <select value={filters.event_type} onChange={(e) => updateFilter("event_type", e.target.value)}>
                  <option value="">Все события</option>
                  {summary.filter_options.event_types.map((eventType) => (
                    <option key={eventType} value={eventType}>
                      {eventType}
                    </option>
                  ))}
                </select>

                <input
                  value={filters.component}
                  onChange={(e) => updateFilter("component", e.target.value)}
                  placeholder="Фильтр по component"
                />
                <input
                  value={filters.search}
                  onChange={(e) => updateFilter("search", e.target.value)}
                  placeholder="Поиск по message/component"
                />

                <select value={filters.sort_by} onChange={(e) => updateFilter("sort_by", e.target.value)}>
                  <option value="criticality">criticality</option>
                  <option value="ts">ts</option>
                  <option value="level">level</option>
                  <option value="event_type">event_type</option>
                  <option value="component">component</option>
                  <option value="row_id">row_id</option>
                </select>

                <select value={filters.sort_order} onChange={(e) => updateFilter("sort_order", e.target.value)}>
                  <option value="desc">desc</option>
                  <option value="asc">asc</option>
                </select>

                <button className="primary compact" onClick={() => void applyFilters()} disabled={loadingRows}>
                  Применить
                </button>
              </div>
            </section>

            <section className="panel">
              <div className="table-header">
                <div className="panel-title">Результаты</div>
                <div className="pagination">
                  <button
                    className="secondary compact"
                    onClick={() => void fetchRows(analysis.analysis_id, rowsState.page - 1)}
                    disabled={rowsState.page <= 1 || loadingRows}
                  >
                    Назад
                  </button>
                  <span>
                    Страница {rowsState.page} / {pageCount}
                  </span>
                  <button
                    className="secondary compact"
                    onClick={() => void fetchRows(analysis.analysis_id, rowsState.page + 1)}
                    disabled={rowsState.page >= pageCount || loadingRows}
                  >
                    Вперед
                  </button>
                </div>
              </div>

              <div className="table-meta">
                {loadingRows ? "Загружаю..." : `Показано ${rowsState.rows.length} из ${rowsState.total} строк`}
              </div>

              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>#</th>
                      <th>ts</th>
                      <th>level</th>
                      <th>component</th>
                      <th>event_type</th>
                      <th>criticality</th>
                      <th>message</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rowsState.rows.map((row) => (
                      <tr key={row.row_id}>
                        <td>{row.row_id}</td>
                        <td>{row.ts || "-"}</td>
                        <td>{row.level || "-"}</td>
                        <td className="mono">{row.component || "-"}</td>
                        <td className="mono">{row.event_type || "-"}</td>
                        <td>{row.criticality.toFixed(4)}</td>
                        <td>{row.message}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          </>
        ) : (
          <section className="empty-state">
            <h2>Интерфейс готов к подключению</h2>
            <p>Выбери датасет, загрузи файл или вставь логи вручную, а затем запусти анализ.</p>
          </section>
        )}
      </main>
    </div>
  );
}
