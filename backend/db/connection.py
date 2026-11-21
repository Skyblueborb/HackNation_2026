"""Połączenie z SQLite. Ścieżka do bazy tylko z env (O2J_DB_PATH) — nigdy
z repozytorium. Domyślnie <repo>/work/o2j.db, w Dockerze /data/o2j.db.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
REPO_ROOT = Path(__file__).resolve().parents[2]


def default_db_path() -> Path:
    raw = os.environ.get("O2J_DB_PATH")
    if raw:
        return Path(raw).expanduser().resolve()
    return (REPO_ROOT / "work" / "o2j.db").resolve()


def connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path is not None else default_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def init_db(db_path: str | Path | None = None) -> Path:
    """Stwórz tabele (idempotentnie). Zwraca ścieżkę do pliku bazy."""
    path = Path(db_path) if db_path is not None else default_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(path)
    try:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        # Migracja baz istniejących przed dodaniem client_doc_id: stara tabela
        # nie dostaje nowej kolumny przez CREATE TABLE IF NOT EXISTS.
        cols = {row[1] for row in conn.execute("PRAGMA table_info(source_documents)")}
        if "client_doc_id" not in cols:
            conn.execute("ALTER TABLE source_documents ADD COLUMN client_doc_id TEXT")
        conn.execute("DROP INDEX IF EXISTS idx_source_documents_token_class")
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_source_documents_client_doc "
            "ON source_documents(client_doc_id) WHERE client_doc_id IS NOT NULL"
        )
        conn.commit()
    finally:
        conn.close()
    return path


@contextmanager
def db(db_path: str | Path | None = None) -> Iterator[sqlite3.Connection]:
    """Kontekst z automatycznym commit / rollback i zamknięciem połączenia."""
    conn = connect(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
