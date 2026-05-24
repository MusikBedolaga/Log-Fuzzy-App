# Log-Fuzzy-App

Приложение для хранения, поиска и анализа логов. Backend на FastAPI считает fuzzy-оценку критичности, хранит логи в SQLite и отдает CRUD/API для UI. Frontend на React дает отдельные экраны для работы с БД и разового анализа файла.

## Возможности

- Подключение SQLite-базы без дополнительных Python-зависимостей.
- Автоматическая инициализация БД через SQL-миграции.
- CRUD для логов: создание, просмотр, обновление, удаление.
- Импорт `.log` файлов из папки `data` в БД без изменения самой папки.
- Поиск логов через БД: текст, источник, уровень, тип события, компонент, criticality.
- Подсветка критичных записей, WARN/ERROR/FATAL и строк с высокой `criticality`.
- Простая аналитика: проблемные компоненты, часто повторяющиеся ошибки, топ критичных записей, сводка по уровням и событиям.
- Сохранен старый сценарий разового анализа датасета, файла или вставленного текста.

## Стек

- Backend: Python, FastAPI, SQLite, pandas, numpy.
- Frontend: React, Vite.
- Анализ: `backend/app/core/log_model.py`.
- БД: `backend/app/db`.

## Быстрый запуск

Команды ниже выполняются из корня проекта `Log-Fuzzy-App`.

### 1. Python-окружение

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 2. Backend

```powershell
$env:PYTHONPATH = "backend"
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Backend будет доступен на `http://127.0.0.1:8000`.

При старте автоматически выполняется `init_db()` и применяются миграции из `backend/app/db/migrations`.

### 3. Frontend

В отдельном терминале:

```powershell
cd frontend
npm install
npm run dev
```

UI будет доступен на `http://127.0.0.1:5173`.

## База данных

По умолчанию используется SQLite-файл:

```text
backend/storage/log_fuzzy.sqlite3
```

Файл БД не коммитится и создается локально. Путь можно переопределить:

```powershell
$env:LOGFUZZY_DB_PATH = "C:\temp\log_fuzzy.sqlite3"
```

Основные таблицы:

- `log_sources` - импортированные источники из `data`.
- `logs` - отдельные строки логов с разобранными полями, fuzzy-факторами и criticality.
- `schema_migrations` - примененные миграции.

Папка `data` не изменяется. Импорт только читает `.log` файлы и сохраняет их строки в таблицу `logs`. Архивы `.tar.gz` не распаковываются.

## Импорт папки data

Через UI: экран `Логи в БД` -> `Импорт data`.

Через API:

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8000/logs/import-data `
  -ContentType "application/json" `
  -Body '{"force": false}'
```

Импорт конкретного датасета:

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8000/logs/import-data `
  -ContentType "application/json" `
  -Body '{"dataset_name": "HDFS_2k.log", "force": true}'
```

`force: true` удаляет старые строки этого источника из БД и импортирует файл заново. Исходный файл в `data` не меняется.

## CRUD API логов

Создать лог:

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8000/logs `
  -ContentType "application/json" `
  -Body '{"source_name":"manual","raw_text":"081109 203615 148 WARN dfs.DataNode$DataXceiver: Got exception while serving blk_123"}'
```

Получить страницу логов:

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/logs?page=1&page_size=50&sort_by=criticality&sort_order=desc"
```

Получить один лог:

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/logs/1"
```

Обновить лог:

```powershell
Invoke-RestMethod `
  -Method Put `
  -Uri http://127.0.0.1:8000/logs/1 `
  -ContentType "application/json" `
  -Body '{"source_name":"manual_fixed","raw_text":"081109 203616 148 ERROR dfs.DataNode$DataXceiver: Failed to serve blk_123"}'
```

Удалить лог:

```powershell
Invoke-RestMethod -Method Delete "http://127.0.0.1:8000/logs/1"
```

## Поиск и фильтрация

Поиск выполняется через SQLite, а не чтением файлов.

Доступные query-параметры `GET /logs`:

- `search` - поиск по raw text, message, component, source name, signature.
- `source_name` - точный источник, например `HDFS_2k.log`.
- `level` - `INFO`, `WARN`, `ERROR`, `FATAL`, `DEBUG`.
- `event_type` - тип события после классификации.
- `component` - частичное совпадение компонента.
- `min_criticality` - минимальная criticality от `0` до `1`.
- `critical_only=true` - только ERROR/FATAL или criticality >= `0.7`.
- `sort_by` - `criticality`, `ts`, `level`, `event_type`, `component`, `source_name`, `id`.
- `sort_order` - `asc` или `desc`.

Пример:

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/logs?search=exception&level=WARN&min_criticality=0.6"
```

## Аналитика

Endpoint:

```text
GET /logs/stats
```

Возвращает:

- `summary` - количество логов, critical, WARN, ERROR/FATAL, средняя criticality.
- `levels` - распределение по уровням.
- `event_types` - топ типов событий.
- `problem_components` - компоненты с большим числом критичных записей.
- `repeated_errors` - часто повторяющиеся ошибки по нормализованной сигнатуре.
- `critical_rows` - самые критичные строки.

UI подсвечивает:

- красным: `ERROR`, `FATAL` или `criticality >= 0.7`;
- желтым: `WARN` или `criticality >= 0.45`;
- нейтрально: остальные записи.

## Старый анализ файлов

Экран `Анализ файла` сохраняет сценарий без записи в БД:

- выбрать `.log` из папки `data`;
- загрузить локальный файл;
- вставить текст вручную;
- получить сводку, histogram, таблицу строк и CSV.

Основные API:

- `GET /datasets`
- `POST /analyze/dataset`
- `POST /analyze/upload`
- `POST /analyze/text`
- `GET /analyses/{analysis_id}/rows`
- `GET /analyses/{analysis_id}/download`

## Структура проекта

```text
Log-Fuzzy-App/
├─ backend/
│  └─ app/
│     ├─ api/
│     │  └─ logs.py              # CRUD, поиск, импорт, статистика
│     ├─ core/
│     │  └─ log_model.py         # парсинг, fuzzy criticality, summary
│     ├─ db/
│     │  ├─ connection.py        # подключение SQLite и запуск миграций
│     │  ├─ repository.py        # отдельный слой работы с БД
│     │  └─ migrations/
│     │     └─ 001_init.sql      # начальная схема
│     └─ main.py                 # FastAPI app и старые endpoint анализа
├─ data/                         # исходные датасеты, не изменяются приложением
├─ frontend/
│  └─ src/
│     ├─ App.jsx                 # UI: БД и анализ файла
│     └─ styles.css
├─ outputs/                      # локальные результаты
├─ requirements.txt
└─ README.md
```

## Проверки

Backend:

```powershell
python -m compileall backend\app
```

Frontend:

```powershell
cd frontend
npm run build
```

## Примечания

- Новых Python-зависимостей не добавлено: используется стандартный `sqlite3`.
- `backend/storage/`, `*.sqlite3`, `frontend/node_modules/` и `frontend/dist/` игнорируются git.
- При повторном импорте без `force` неизмененные файлы пропускаются по размеру, времени изменения и количеству импортированных строк.


Вопервых подгрузка файлов с логами.
Во вторых при добавлении одного лога возможность присваивание ему статуса
в анализ файла добавить в фильтры уровни логов и вообще какого хуя работает хуево