-- Schemat bazy Odwołania2json.
--
-- Cztery magazyny JSON:
--   1. json_odwolanie
--   2. json_pelnomocnictwo
--   3. json_przelew
--   4. correction_sessions + correction_items  (źle odczytane + poprawki)
--
-- Wyniki modelu w magazynach 1-3 są NIEZMIENNE. Poprawki nie nadpisują ich —
-- trafiają do magazynu 4 jako pary (predicted_json, corrected_json), co
-- pozwala dalej mierzyć F1 i jednocześnie zbierać dane do douczania modelu.

CREATE TABLE IF NOT EXISTS jobs (
    id              TEXT PRIMARY KEY,
    doc_sha256      TEXT,
    status          TEXT NOT NULL DEFAULT 'queued'
                    CHECK (status IN ('queued', 'processing', 'done', 'failed')),
    step            INTEGER NOT NULL DEFAULT 0,
    progress        INTEGER NOT NULL DEFAULT 0,
    model_version   TEXT,
    config_version  TEXT,
    error           TEXT,
    created_at      TEXT NOT NULL,
    finished_at     TEXT
);

-- Jedno źródło PDF = jeden wiersz. Samego pliku nie trzymamy w bazie (BLOB),
-- tylko ścieżkę na dysku. text_p1_3 zasila retrieval few-shot.
CREATE TABLE IF NOT EXISTS source_documents (
    id              TEXT PRIMARY KEY,
    job_id          TEXT REFERENCES jobs(id) ON DELETE SET NULL,
    client_token    TEXT,
    client_doc_id   TEXT,
    doc_class       TEXT NOT NULL
                    CHECK (doc_class IN ('odwolanie', 'pelnomocnictwo', 'przelew')),
    source_name     TEXT,
    pdf_sha256      TEXT,
    pdf_path        TEXT,
    page_count      INTEGER,
    text_p1_3       TEXT,
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_source_documents_class
    ON source_documents(doc_class);
CREATE INDEX IF NOT EXISTS idx_source_documents_job
    ON source_documents(job_id);
-- Uwaga: unikalny indeks po (client_token, client_doc_id) jest zakładany
-- w connection.init_db() PO migracji dodającej kolumny do starszych baz.
-- Sam client_doc_id NIE jest unikalny — dwóch klientów może użyć tego samego
-- identyfikatora pliku.

-- MAGAZYN 1: odwołanie -----------------------------------------------------
CREATE TABLE IF NOT EXISTS json_odwolanie (
    document_id     TEXT PRIMARY KEY REFERENCES source_documents(id) ON DELETE CASCADE,
    canonical_json  TEXT NOT NULL CHECK (json_valid(canonical_json)),
    provenance_json TEXT,
    model_version   TEXT,
    config_version  TEXT,
    created_at      TEXT NOT NULL
);

-- MAGAZYN 2: pełnomocnictwo -------------------------------------------------
CREATE TABLE IF NOT EXISTS json_pelnomocnictwo (
    document_id     TEXT PRIMARY KEY REFERENCES source_documents(id) ON DELETE CASCADE,
    canonical_json  TEXT NOT NULL CHECK (json_valid(canonical_json)),
    provenance_json TEXT,
    model_version   TEXT,
    config_version  TEXT,
    created_at      TEXT NOT NULL
);

-- MAGAZYN 3: przelew -------------------------------------------------------
CREATE TABLE IF NOT EXISTS json_przelew (
    document_id     TEXT PRIMARY KEY REFERENCES source_documents(id) ON DELETE CASCADE,
    canonical_json  TEXT NOT NULL CHECK (json_valid(canonical_json)),
    provenance_json TEXT,
    model_version   TEXT,
    config_version  TEXT,
    created_at      TEXT NOT NULL
);

-- MAGAZYN 4: błędne odczyty + poprawki -------------------------------------
-- Pełne snapshoty JSON przed i po poprawce.
CREATE TABLE IF NOT EXISTS correction_sessions (
    id              TEXT PRIMARY KEY,
    document_id     TEXT NOT NULL REFERENCES source_documents(id) ON DELETE CASCADE,
    predicted_json  TEXT NOT NULL CHECK (json_valid(predicted_json)),
    corrected_json  TEXT NOT NULL CHECK (json_valid(corrected_json)),
    reviewer        TEXT,
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_correction_sessions_document
    ON correction_sessions(document_id);
CREATE INDEX IF NOT EXISTS idx_correction_sessions_created
    ON correction_sessions(created_at);

-- Różnice per pole — tu zapadają flagi jakości używane przy eksporcie treningowym:
--   validator_ok = 1  -> wartość przeszła sumę kontrolną (NIP/NRB/PESEL/...)
--   grounded_ok  = 1  -> wartość występuje w tekście źródłowym
--   NULL             -> nie dotyczy / brak tekstu do sprawdzenia
CREATE TABLE IF NOT EXISTS correction_items (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT NOT NULL REFERENCES correction_sessions(id) ON DELETE CASCADE,
    field_path      TEXT NOT NULL,
    predicted_value TEXT,
    corrected_value TEXT,
    method          TEXT,
    confidence      REAL,
    page            INTEGER,
    bbox            TEXT,
    quote           TEXT,
    validator_ok    INTEGER CHECK (validator_ok IN (0, 1)),
    grounded_ok     INTEGER CHECK (grounded_ok IN (0, 1)),
    model_version   TEXT,
    config_version  TEXT
);

CREATE INDEX IF NOT EXISTS idx_correction_items_session
    ON correction_items(session_id);
CREATE INDEX IF NOT EXISTS idx_correction_items_field
    ON correction_items(field_path);

-- Zatwierdzone dokumenty do dynamicznego few-shot (poziom 1 planu AI).
CREATE TABLE IF NOT EXISTS approved_docs (
    doc_id          TEXT PRIMARY KEY REFERENCES source_documents(id) ON DELETE CASCADE,
    doc_class       TEXT NOT NULL,
    text_p1_3       TEXT,
    final_json      TEXT NOT NULL CHECK (json_valid(final_json)),
    embedding       TEXT,
    created_at      TEXT NOT NULL
);
