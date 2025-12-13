-- tw database schema
-- Stores issues and annotations for the tw issue tracker

CREATE TABLE IF NOT EXISTS issues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid TEXT NOT NULL UNIQUE,
    tw_id TEXT NOT NULL UNIQUE,
    tw_type TEXT NOT NULL,
    title TEXT NOT NULL,
    tw_status TEXT NOT NULL,
    tw_parent TEXT,
    tw_body TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS annotations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    issue_id INTEGER NOT NULL,
    type TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    message TEXT NOT NULL,
    FOREIGN KEY (issue_id) REFERENCES issues(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS issue_refs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_issue_id INTEGER NOT NULL,
    target_tw_id TEXT,
    FOREIGN KEY (source_issue_id) REFERENCES issues(id) ON DELETE CASCADE,
    FOREIGN KEY (target_tw_id) REFERENCES issues(tw_id) ON DELETE SET NULL
);

-- Indexes for performance
CREATE UNIQUE INDEX IF NOT EXISTS idx_issues_uuid ON issues(uuid);
CREATE INDEX IF NOT EXISTS idx_issues_tw_id ON issues(tw_id);
CREATE INDEX IF NOT EXISTS idx_issues_tw_parent ON issues(tw_parent);
CREATE INDEX IF NOT EXISTS idx_annotations_issue_id ON annotations(issue_id);
CREATE INDEX IF NOT EXISTS idx_annotations_type ON annotations(type);
CREATE INDEX IF NOT EXISTS idx_issue_refs_source ON issue_refs(source_issue_id);
CREATE INDEX IF NOT EXISTS idx_issue_refs_target ON issue_refs(target_tw_id);
