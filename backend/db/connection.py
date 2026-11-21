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
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def _repair_foreign_keys(conn: sqlite3.Connection) -> None:
    """Napraw uszkodzone klucze obce wskazujące na ``source_documents_old``.

    Starsza wersja migracji zmieniała nazwę tabeli ``source_documents`` bez
    ``legacy_alter_table``, przez co SQLite przepisał FK-i w pozostałych
    tabelach na nazwę tymczasową. Po usunięciu starej tabeli zapisywanie
    wyników kończyło się błędem ``no such table: main.source_documents_old``.
    Naprawa przebudowuje uszkodzone tabele z zachowaniem wszystkich wierszy.
    """
    broken = conn.execute(
        "SELECT name, sql FROM sqlite_master "
        "WHERE type='table' AND sql LIKE '%source_documents_old%'"
    ).fetchall()
    if not broken:
        return

    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("PRAGMA legacy_alter_table = ON")
    try:
        conn.execute("BEGIN")
        for name, sql in broken:
            tmp = f"{name}__fk_repair"
            conn.execute(f'ALTER TABLE "{name}" RENAME TO "{tmp}"')
            conn.execute(sql.replace('"source_documents_old"', "source_documents"))
            cols = [row[1] for row in conn.execute(f'PRAGMA table_info("{tmp}")')]
            col_list = ", ".join(f'"{c}"' for c in cols)
            conn.execute(
                f'INSERT INTO "{name}" ({col_list}) SELECT {col_list} FROM "{tmp}"'
            )
            conn.execute(f'DROP TABLE "{tmp}"')
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.execute("PRAGMA legacy_alter_table = OFF")
        conn.execute("PRAGMA foreign_keys = ON")


def _dedupe_source_documents(conn: sqlite3.Connection) -> None:
    """Merge legacy duplicates before creating the unique (token, doc id) index.

    Older check-then-write upserts could insert two source rows for the same
    key. Keep the oldest row and move its dependent records over before deleting
    the extras, so CREATE UNIQUE INDEX cannot fail on an existing database.
    """
    groups = conn.execute(
        "SELECT client_token, client_doc_id, GROUP_CONCAT(id) AS ids "
        "FROM source_documents "
        "WHERE client_token IS NOT NULL AND client_doc_id IS NOT NULL "
        "GROUP BY client_token, client_doc_id HAVING COUNT(*) > 1"
    ).fetchall()
    tables = (
        "json_odwolanie",
        "json_pelnomocnictwo",
        "json_przelew",
        "correction_sessions",
        "approved_docs",
    )
    for group in groups:
        keep = group["ids"].split(",")[0]
        for extra in group["ids"].split(",")[1:]:
            for table in tables:
                conn.execute(
                    f"DELETE FROM {table} WHERE document_id = ? "
                    f"AND EXISTS (SELECT 1 FROM {table} WHERE document_id = ?)",
                    (extra, keep),
                )
                conn.execute(
                    f"UPDATE {table} SET document_id = ? WHERE document_id = ?",
                    (keep, extra),
                )
            conn.execute("DELETE FROM source_documents WHERE id = ?", (extra,))


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

        # Samonaprawa bazy zepsutej przez starszą migrację (FK -> ..._old).
        _repair_foreign_keys(conn)
        # Przy przebudowie tabel znikają ich indeksy — odtwórz z schematu.
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))

        _dedupe_source_documents(conn)
        conn.execute("DROP INDEX IF EXISTS idx_source_documents_token_class")
        conn.execute("DROP INDEX IF EXISTS idx_source_documents_client_doc")
        # client_doc_id is only unique inside one client_token. Keying on the
        # id alone lets two clients (or two classes) silently merge documents.
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_source_documents_client_key "
            "ON source_documents(client_token, client_doc_id) "
            "WHERE client_token IS NOT NULL AND client_doc_id IS NOT NULL"
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
