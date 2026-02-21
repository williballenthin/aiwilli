CREATE TABLE IF NOT EXISTS sessions (
  source TEXT NOT NULL,
  session_id TEXT NOT NULL,
  transcript_path TEXT NOT NULL,
  project TEXT,
  cwd TEXT,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  last_ingested_line INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (source, session_id)
);

CREATE TABLE IF NOT EXISTS messages (
  source TEXT NOT NULL,
  session_id TEXT NOT NULL,
  source_message_id TEXT NOT NULL,
  line_no INTEGER NOT NULL,
  role TEXT NOT NULL,
  ts TEXT NOT NULL,
  project TEXT,
  cwd TEXT,
  transcript_path TEXT NOT NULL,
  content_text TEXT NOT NULL,
  raw_type TEXT,
  is_sidechain INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (source, session_id, source_message_id)
);

CREATE TABLE IF NOT EXISTS extractor_progress (
  extractor_name TEXT NOT NULL,
  source TEXT NOT NULL,
  session_id TEXT NOT NULL,
  last_processed_line INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (extractor_name, source, session_id)
);

CREATE TABLE IF NOT EXISTS reflector_state (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  last_reflected_at TEXT,
  last_reflected_obs_date TEXT
);
