CREATE TABLE IF NOT EXISTS schema_migrations (
  version TEXT PRIMARY KEY,
  applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT OR IGNORE INTO schema_migrations(version) VALUES ('001_initial');

CREATE TABLE IF NOT EXISTS project_meta (
  project_id TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS records (
  project_id TEXT NOT NULL,
  entity_type TEXT NOT NULL,
  record_id TEXT NOT NULL,
  slug TEXT,
  title TEXT NOT NULL,
  summary TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  schema_version TEXT NOT NULL,
  source_origin TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  created_by TEXT NOT NULL,
  updated_by TEXT NOT NULL,
  PRIMARY KEY (project_id, entity_type, record_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_records_slug
  ON records(project_id, entity_type, slug)
  WHERE slug IS NOT NULL AND slug != '';

CREATE INDEX IF NOT EXISTS idx_records_type_status
  ON records(project_id, entity_type, status, updated_at);

CREATE TABLE IF NOT EXISTS binaries (
  binary_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  display_name TEXT NOT NULL,
  file_path TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_binaries_project_id
  ON binaries(project_id);

CREATE TABLE IF NOT EXISTS functions (
  project_id TEXT NOT NULL,
  binary_id TEXT NOT NULL,
  function_id TEXT NOT NULL,
  address TEXT NOT NULL,
  address_norm TEXT NOT NULL,
  raw_name TEXT NOT NULL,
  current_name TEXT NOT NULL,
  summary TEXT NOT NULL,
  behavior_description TEXT NOT NULL,
  important_variables_json TEXT NOT NULL DEFAULT '[]',
  used_apis_json TEXT NOT NULL DEFAULT '[]',
  strings_json TEXT NOT NULL DEFAULT '[]',
  constants_json TEXT NOT NULL DEFAULT '[]',
  confidence REAL,
  source_origin TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  created_by TEXT NOT NULL,
  updated_by TEXT NOT NULL,
  conflict_status TEXT NOT NULL DEFAULT 'clean',
  PRIMARY KEY (project_id, binary_id, function_id)
);

CREATE INDEX IF NOT EXISTS idx_functions_address
  ON functions(project_id, binary_id, address_norm);

CREATE INDEX IF NOT EXISTS idx_functions_name
  ON functions(project_id, current_name);

CREATE INDEX IF NOT EXISTS idx_functions_updated_at
  ON functions(project_id, updated_at);

CREATE TABLE IF NOT EXISTS structures (
  project_id TEXT NOT NULL,
  binary_id TEXT NOT NULL,
  structure_id TEXT NOT NULL,
  raw_name TEXT NOT NULL,
  current_name TEXT NOT NULL,
  summary TEXT NOT NULL,
  fields_json TEXT NOT NULL DEFAULT '[]',
  source_origin TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  created_by TEXT NOT NULL,
  updated_by TEXT NOT NULL,
  PRIMARY KEY (project_id, structure_id)
);

CREATE INDEX IF NOT EXISTS idx_structures_project_binary
  ON structures(project_id, binary_id);

CREATE INDEX IF NOT EXISTS idx_structures_name
  ON structures(project_id, current_name);

CREATE TABLE IF NOT EXISTS entity_facts (
  fact_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  entity_type TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  fact_text TEXT NOT NULL,
  source_origin TEXT NOT NULL,
  created_at TEXT NOT NULL,
  created_by TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_entity_facts_lookup
  ON entity_facts(project_id, entity_type, entity_id);

CREATE TABLE IF NOT EXISTS hypotheses (
  hypothesis_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  binary_id TEXT,
  subject_entity_type TEXT,
  subject_entity_id TEXT,
  title TEXT,
  statement TEXT NOT NULL,
  status TEXT NOT NULL,
  confidence REAL,
  source_origin TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  created_by TEXT NOT NULL,
  updated_by TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_hypotheses_lookup
  ON hypotheses(project_id, subject_entity_type, subject_entity_id, status);

CREATE TABLE IF NOT EXISTS evidence (
  evidence_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  entity_type TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  evidence_type TEXT NOT NULL,
  address_start TEXT,
  address_end TEXT,
  xref TEXT,
  block_ref TEXT,
  description TEXT NOT NULL,
  excerpt TEXT,
  attachment_id TEXT,
  source_origin TEXT NOT NULL,
  created_at TEXT NOT NULL,
  created_by TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_evidence_lookup
  ON evidence(project_id, entity_type, entity_id);

CREATE TABLE IF NOT EXISTS attachments (
  attachment_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  relative_path TEXT NOT NULL,
  media_type TEXT,
  size_bytes INTEGER,
  created_at TEXT NOT NULL,
  created_by TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tags (
  project_id TEXT NOT NULL,
  tag_name TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (project_id, tag_name)
);

CREATE TABLE IF NOT EXISTS entity_tags (
  project_id TEXT NOT NULL,
  entity_type TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  tag_name TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (project_id, entity_type, entity_id, tag_name)
);

CREATE INDEX IF NOT EXISTS idx_entity_tags_lookup
  ON entity_tags(project_id, entity_type, entity_id);

CREATE TABLE IF NOT EXISTS relations (
  relation_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  from_entity_type TEXT NOT NULL,
  from_entity_id TEXT NOT NULL,
  to_entity_type TEXT NOT NULL,
  to_entity_id TEXT NOT NULL,
  relation_type TEXT NOT NULL,
  created_at TEXT NOT NULL,
  created_by TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_relations_from
  ON relations(project_id, from_entity_type, from_entity_id);

CREATE INDEX IF NOT EXISTS idx_relations_to
  ON relations(project_id, to_entity_type, to_entity_id);

CREATE TABLE IF NOT EXISTS duplicate_candidates (
  candidate_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  entity_type TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  duplicate_entity_id TEXT NOT NULL,
  reason TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS entity_versions (
  version_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  entity_type TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  version_number INTEGER NOT NULL,
  snapshot_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  created_by TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_entity_versions_unique
  ON entity_versions(project_id, entity_type, entity_id, version_number);

CREATE TABLE IF NOT EXISTS audit_log (
  audit_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  entity_type TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  action TEXT NOT NULL,
  actor_type TEXT NOT NULL,
  actor_id TEXT NOT NULL,
  source_origin TEXT NOT NULL,
  request_id TEXT,
  summary TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_lookup
  ON audit_log(project_id, entity_type, entity_id, created_at);

CREATE TABLE IF NOT EXISTS pending_changes (
  pending_change_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  entity_type TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  operation TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  created_by TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS search_documents (
  document_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  entity_type TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  title_text TEXT NOT NULL,
  body_text TEXT NOT NULL,
  tag_text TEXT NOT NULL,
  address_text TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_search_documents_lookup
  ON search_documents(project_id, entity_type, entity_id);

CREATE VIRTUAL TABLE IF NOT EXISTS search_documents_fts USING fts5(
  document_id UNINDEXED,
  project_id UNINDEXED,
  entity_type UNINDEXED,
  entity_id UNINDEXED,
  title_text,
  body_text,
  tag_text,
  address_text
);
