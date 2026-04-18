## План: offline-first RE Knowledge Base с HTTP API, MCP и дальнейшим GUI

### Summary
- Проект строится как локальное Windows-first Python-приложение с общим core-слоем и двумя адаптерами поверх него: HTTP API и MCP server.
- Базовая топология хранения: один глобальный `app_config.json` c реестром проектов и отдельная папка на каждый проект с собственными `project.db`, `attachments/`, `exports/`, `backups/`, `logs/`. Это даёт жёсткую изоляцию, простой backup/restore и естественную привязку одного MCP-порта к одному проекту.
- Базовая топология рантайма: один HTTP/GUI процесс на проект и один MCP HTTP процесс на проект; оба используют один и тот же сервисный слой и один `ProjectContext`.
- Выбранный стек: `CPython 3.11 x64`, `sqlite3`/FTS5 и максимум stdlib; из внешних зависимостей только `pydantic` для строгой валидации и JSON-схем, `starlette` + `uvicorn` для локального HTTP/GUI, официальный `mcp` Python SDK для протокольной совместимости.
- Реализация идёт фазами: `config + schema + models + services` -> `HTTP API` -> `MCP` -> `import/export` -> `backup/restore` -> `GUI`.

### Architecture
- Кодовая структура:

```text
mcp-memory/
  pyproject.toml
  README.md
  src/mcp_memory/
    cli/
    config/
    domain/
    storage/
    services/
    search/
    api/
    mcp/
    importers/
    backup/
    gui/
  sql/
    migrations/
  tests/
  scripts/
```

- `config`: `AppConfig`, `ProjectConfig`, `ProjectRegistry`, загрузка/сохранение JSON-конфига, генерация connection config для агента, выбор data root через `MCP_MEMORY_HOME` или `%LOCALAPPDATA%\\mcp-memory`.
- `domain`: типы `FunctionRecord`, `StructureRecord`, `HypothesisRecord`, `EvidenceRecord`, `Relation`, `Tag`, `VersionEntry`, `AuditEntry`, `PendingChange`, enum-ы `HypothesisStatus`, `ActorType`, `OriginType`, `WriteMode`.
- `storage`: фабрика SQLite-соединений, миграции без Alembic, репозитории, транзакции, сборка snapshot-версий, файловое хранилище вложений по относительным путям.
- `services`: CRUD, versioning, audit, confirm-flow для агентских записей, импорт/экспорт, backup/restore, сборка карточек сущностей, политика конфликтов адресов и дедупликации.
- `search`: exact name/address, FTS5, tags, graph traversal 1–2 hops, reranking, optional `SemanticSearchProvider` интерфейс без обязательной реализации в MVP.
- `api`: один локальный JSON API на проект; позже в этот же процесс добавляется GUI на server-rendered шаблонах с минимальным JS.
- `mcp`: отдельный MCP HTTP сервер на проект с тем же набором use case-ов, что и у HTTP API.
- Компромисс: `Starlette` выбран вместо FastAPI/Flask, потому что он легче, достаточно хорош для локального JSON API и SSR GUI, а `pydantic` закрывает строгую валидацию без ручного парсинга.

### SQLite and Data Model
- Контрольные таблицы: `schema_migrations`, `project_meta`, `binaries`, `pending_changes`.
- Основные таблицы: `functions`, `structures`, `hypotheses`, `evidence`, `attachments`, `relations`, `entity_facts`, `tags`, `entity_tags`, `duplicate_candidates`, `entity_versions`, `audit_log`, `search_documents`.
- `functions` хранит базовые поля карточки и bounded JSON-поля для `important_variables`, `used_apis`, `strings`, `constants`; `callers`, `callees`, `related_entities` не дублируются как основной источник истины, а собираются из `relations`.
- `structures` хранит заголовок структуры и описание; поля структуры выносятся в `structure_members`, чтобы были пригодны для поиска и эволюции.
- `hypotheses` единая таблица и для глобальных гипотез, и для привязанных к сущности; поля: `hypothesis_id`, `project_id`, `binary_id nullable`, `subject_entity_type nullable`, `subject_entity_id nullable`, `title`, `statement`, `status`, `confidence`, `source_origin`, `created_*`, `updated_*`.
- `entity_facts` хранит observed facts отдельно от hypotheses для любой сущности; это обязательное разделение на уровне модели и API.
- `evidence` хранит тип, адресный диапазон, xref/block метаданные, описание, опциональный короткий excerpt и ссылку на `attachments`; полные сырые дампы в БД не хранятся.
- `entity_versions` хранит полный JSON snapshot актуальной сущности на каждый успешный commit; `audit_log` хранит действие, актор, origin/source, request_id и краткий diff summary.
- `pending_changes` нужен для режима `write_mode=confirm`: MCP/API создаёт proposal, а отдельный confirm/reject commit-ит или отклоняет изменение.
- FTS: один `search_documents_fts` на базе `search_documents` с агрегированным текстом `title_text/body_text/tag_text/address_text`; обновление индекса делает сервисный слой в той же транзакции, а не SQL-триггеры.
- Индексы: уникальный `(project_id, binary_id, function_id)`; уникальный `(project_id, structure_id)`; индекс `(project_id, binary_id, address_norm)`; индексы на `status`, `tags`, `relations(from_*)`, `relations(to_*)`, `updated_at`; FTS5 `bm25`.
- Политика address conflict: запись по умолчанию требует уникальный адрес в рамках `binary_id`; при явном `allow_conflict=true` коллизия не merge-ится, а обе записи получают флаг конфликта и строку в `duplicate_candidates`.
- Политика размеров по умолчанию: `summary <= 1024`, `behavior_description <= 8192`, `fact/hypothesis/evidence description <= 2048`, `evidence excerpt <= 4096`, token-like item `<= 256`, не более `100` элементов в каждой list-категории, attachment `<= 10 MiB`.

### API and MCP Surface
- Канонические DTO: `FunctionUpsert`, `StructureUpsert`, `HypothesisCreate`, `EvidenceCreate`, `SearchRequest`, `RecordEnvelope`, `RelationEnvelope`, `ImportBundle`, `ExportBundle`, `BackupResult`, `ProjectConnectionConfig`, `PendingChangeEnvelope`.
- `FunctionUpsert` включает: `function_id`, `binary_id`, `address`, `raw_name`, `current_name`, `summary`, `behavior_description`, `confidence`, `important_variables[]`, `used_apis[]`, `strings[]`, `constants[]`, `tags[]`, `observed_facts[]`, `source_origin`, `allow_conflict`.
- `RecordEnvelope` возвращает только актуальную версию сущности плюс `facts`, `hypotheses`, `relations`, `evidence`, `duplicates`, `audit_summary`; история версий отдельным endpoint/tool не отдаётся по умолчанию агенту.
- HTTP endpoints: `POST /search`, `GET /functions/{id}`, `POST /functions`, `PATCH /functions/{id}`, `GET/POST/PATCH /structures`, `GET/POST/PATCH /hypotheses`, `POST /evidence`, `GET /relations/{entity}`, `POST /import/json`, `POST /export/json`, `POST /backup`, `POST /restore`, `GET /project/config`, `POST /pending/{id}/confirm`, `POST /pending/{id}/reject`, `GET/POST /binaries`.
- MCP tools паритетны HTTP: `search_records`, `get_record`, `get_related`, `create_function`, `update_function`, `create_structure`, `update_structure`, `create_hypothesis`, `add_evidence`, `import_json`, `export_json`, `backup_project`, `get_project_config`, `confirm_change`, `reject_change`.
- Валидация: нормализация адреса в canonical hex, строгие enum-ы статусов и actor type, обязательность `summary` и `behavior_description` для function, запрет пустых tags/facts/hypotheses, проверка project/binary scope на каждом write.
- Ошибки: `400 validation_error`, `404 not_found`, `409 uniqueness_conflict/address_conflict`, `409 pending_confirmation_required`, `422 invalid_status_transition`, `503 semantic_search_unavailable` только если caller явно потребовал semantic-only режим.

### MVP, Tests, Assumptions
- MVP включает: project registry, per-project SQLite schema, CRUD для `functions/structures/hypotheses/evidence`, facts/hypotheses separation, tags/relations, FTS5 search, graph traversal 1–2 hops, JSON import/export, backup/restore, HTTP API, MCP server, confirm-vs-auto write mode, version log и audit trail.
- После MVP откладываются: полноценный GUI, visual graph UI, embeddings/semantic provider implementation, unified multi-project server router, IDA importer, merge conflicting records, auth, cloud sync.
- Этап 1: bootstrap и CLI-команды `init-app`, `create-project`, `run-api`, `run-mcp`, `import-json`, `export-json`, `backup`.
- Этап 2: миграции, репозитории, сервисы карточек, snapshot versioning, audit, pending change flow.
- Этап 3: HTTP API и контрактные схемы.
- Этап 4: MCP tools с паритетом операций и той же политикой валидации.
- Этап 5: JSON importer/exporter и файловый backup/restore.
- Этап 6: GUI на server-rendered шаблонах; first-run wizard, список проектов, поиск, карточка сущности, история версий, настройка API/MCP.
- Тесты: миграции на пустой БД; project isolation; CRUD + version + audit; confirm-mode proposals; FTS + exact + relations fallback без embeddings; import/export roundtrip; backup/restore с вложениями; address conflict без auto-merge; MCP/HTTP parity.
- Допущения по умолчанию: базовый runtime — `CPython 3.11 x64`; SQLite с FTS5 доступен; текущая среда пока без установленного Python, поэтому первым артефактом реализации должны стать bootstrap-инструкции и offline install script; GUI обслуживается тем же HTTP приложением, а MCP всегда остаётся отдельным портом на проект; cross-project search не входит в MVP.
