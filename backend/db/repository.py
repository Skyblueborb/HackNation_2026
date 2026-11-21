"""Repozytorium SQLite.

Zasady:
  * cztery osobne magazyny JSON (3x wynik modelu + 1x poprawki),
  * wynik modelu jest NIEZMIENNY — poprawki idą tylko do magazynu 4,
  * każda operacja przyjmuje otwarte połączenie sqlite3 (transakcję
    ogarnia ``backend.db.connection.db``),
  * ścieżka do pliku PDF zapisywana jest jako tekst, nigdy BLOB.
"""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from o2jcore.normalize.checksums import (
    krs_valid,
    nip_valid,
    nrb_valid,
    pesel_valid,
    regon_valid,
)

# Mapa nazwa klasy (zurecznik API) -> tabela z magazynem 1/2/3.
# Whitelist chroni przed wstrzyknięciem nazwy tabeli do SQL-a.
CLASS_TO_TABLE: dict[str, str] = {
    "odwolanie": "json_odwolanie",
    "pelnomocnictwo": "json_pelnomocnictwo",
    "przelew": "json_przelew",
}

# Mapa nazwa klasy z API -> id specyfikacji YAML (używane przy walidacji).
CLASS_TO_SPEC_ID: dict[str, str] = {
    "odwolanie": "odwolanie",
    "pelnomocnictwo": "pelnomocnictwo",
    "przelew": "potwierdzenie_przelewu",
}

_TOKEN_RE = re.compile(r"([^.\[\]]+)|\[(\d*)\]")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=False)


@contextmanager
def _immediate(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Serialize a read-modify-write with BEGIN IMMEDIATE.

    When the caller already opened a transaction (the usual case inside
    ``db()``), a savepoint keeps the critical section atomic without trying
    to nest BEGIN. Fresh connections take the write lock up front.
    """
    if conn.in_transaction:
        name = "_o2j_correction"
        conn.execute(f"SAVEPOINT {name}")
        try:
            yield conn
        except Exception:
            conn.execute(f"ROLLBACK TO {name}")
            conn.execute(f"RELEASE {name}")
            raise
        else:
            conn.execute(f"RELEASE {name}")
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except Exception:
        conn.rollback()
        raise
    else:
        conn.commit()


def _table(doc_class: str) -> str:
    try:
        return CLASS_TO_TABLE[doc_class]
    except KeyError as exc:
        raise ValueError(
            f"unknown doc_class {doc_class!r}; expected one of {sorted(CLASS_TO_TABLE)}"
        ) from exc


# ---------------------------------------------------------------------------
# Ścieżki pól: Odwolujacy[0].nip, mocodawca[].podpisujacy[].imie_nazwisko
# ---------------------------------------------------------------------------


def _tokens(path: str) -> list[str | int]:
    out: list[str | int] = []
    for match in _TOKEN_RE.finditer(path):
        key, idx = match.group(1), match.group(2)
        if key is not None:
            out.append(key)
        else:
            out.append(0 if idx == "" else int(idx))  # '[]' -> indeks 0
    return out


def set_by_path(obj: Any, path: str, value: Any) -> Any:
    """Ustaw wartość pod ścieżką kropkową z indeksami list.

    Obsługuje ``a.b[0].c`` oraz skrót ``a[].b`` (traktowany jako indeks 0).
    Tworzy brakujące słowniki i listy po drodze.
    """
    toks = _tokens(path)
    if not toks:
        raise ValueError("empty field_path")
    cur = obj
    for i, tok in enumerate(toks[:-1]):
        nxt = toks[i + 1]
        if isinstance(tok, int):
            if not isinstance(cur, list):
                raise ValueError(f"expected list at {tok!r} in {path!r}")
            while len(cur) <= tok:
                cur.append({} if isinstance(nxt, str) else [])
            cur = cur[tok]
        else:
            if not isinstance(cur, dict):
                raise ValueError(f"expected object at {tok!r} in {path!r}")
            if tok not in cur or cur[tok] is None:
                cur[tok] = [] if isinstance(nxt, int) else {}
            cur = cur[tok]
    last = toks[-1]
    if isinstance(last, int):
        if not isinstance(cur, list):
            raise ValueError(f"expected list at {last!r} in {path!r}")
        while len(cur) <= last:
            cur.append(None)
        cur[last] = value
    else:
        if not isinstance(cur, dict):
            raise ValueError(f"expected object at {last!r} in {path!r}")
        cur[last] = value
    return obj


def diff_json(a: Any, b: Any, prefix: str = "") -> list[tuple[str, Any, Any]]:
    """Płytka rekurencyjna różnica: [(ścieżka, wartość_a, wartość_b)].

    Listy porównywane są po indeksie (kolejność w kanonie ma znaczenie).
    """
    out: list[tuple[str, Any, Any]] = []
    if isinstance(a, dict) and isinstance(b, dict):
        for key in sorted(set(a) | set(b)):
            path = f"{prefix}.{key}" if prefix else key
            if key not in a or key not in b:
                out.append((path, a.get(key), b.get(key)))
            else:
                out.extend(diff_json(a[key], b[key], path))
    elif isinstance(a, list) and isinstance(b, list):
        for i in range(max(len(a), len(b))):
            path = f"{prefix}[{i}]"
            if i >= len(a) or i >= len(b):
                out.append((path, a[i] if i < len(a) else None, b[i] if i < len(b) else None))
            else:
                out.extend(diff_json(a[i], b[i], path))
    elif a != b:
        out.append((prefix, a, b))
    return out


# ---------------------------------------------------------------------------
# Flagi jakości poprawki (bramka przed douczaniem)
# ---------------------------------------------------------------------------


def _leaf_key(field_path: str) -> str:
    key = field_path.rsplit(".", 1)[-1]
    return re.sub(r"\[\d*\]$", "", key)


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return _dumps(value)
    return str(value)


def validator_ok(field_path: str, value: Any) -> bool:
    """Czy poprawka przeszła sumę kontrolną właściwą dla danego pola.

    Pola bez sumy kontrolnej zwracają True (brak powodu do odrzucenia).
    """
    if value is None:
        return True
    key = _leaf_key(field_path)
    text = _as_text(value)
    checks = {
        "nip": nip_valid,
        "regon": regon_valid,
        "krs": krs_valid,
        "na_rachunek": nrb_valid,
        "z_rachunku": nrb_valid,
        "pesel": pesel_valid,
    }
    check = checks.get(key)
    return True if check is None else bool(check(text))


def grounded_ok(field_path: str, value: Any, text_p1_3: str | None) -> bool | None:
    """Czy wartość występuje w tekście źródłowym.

    None oznacza „nieznane" (brak tekstu) — takie pary są dopuszczane do
    eksportu treningowego, ale mają w nim pole ``grounded`` z wartością null.
    """
    if not text_p1_3:
        return None
    raw = _as_text(value).strip()
    if not raw:
        return True  # puste pole nie wymaga ugruntowania
    haystack = text_p1_3
    if raw in haystack:
        return True
    digits = re.sub(r"\D", "", raw)
    if len(digits) >= 6 and digits in re.sub(r"\D", "", haystack):
        return True
    return False


# ---------------------------------------------------------------------------
# Zadania i dokumenty źródłowe
# ---------------------------------------------------------------------------


def get_job(conn: sqlite3.Connection, job_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return dict(row) if row else None


def _find_keyed_document(
    conn: sqlite3.Connection, client_token: str | None, client_doc_id: str | None
) -> sqlite3.Row | None:
    if client_doc_id is None:
        return None
    return conn.execute(
        "SELECT * FROM source_documents WHERE client_token IS ? AND client_doc_id = ?",
        (client_token, client_doc_id),
    ).fetchone()


def _touch_source_document(
    conn: sqlite3.Connection,
    doc_id: str,
    *,
    doc_class: str,
    job_id: str | None,
    source_name: str | None,
    pdf_sha256: str | None,
    pdf_path: str | None,
    page_count: int | None,
    text_p1_3: str | None,
) -> None:
    # doc_class is part of the update: a re-ingest may reclassify the file.
    updates = ["doc_class = ?"]
    values: list[Any] = [doc_class]
    for col, val in (
        ("job_id", job_id), ("source_name", source_name), ("pdf_sha256", pdf_sha256),
        ("pdf_path", pdf_path), ("page_count", page_count), ("text_p1_3", text_p1_3),
    ):
        if val is not None:
            updates.append(f"{col} = ?")
            values.append(val)
    values.append(doc_id)
    conn.execute(f"UPDATE source_documents SET {', '.join(updates)} WHERE id = ?", values)


def upsert_source_document(
    conn: sqlite3.Connection,
    *,
    doc_class: str,
    client_token: str | None = None,
    client_doc_id: str | None = None,
    job_id: str | None = None,
    source_name: str | None = None,
    pdf_sha256: str | None = None,
    pdf_path: str | None = None,
    page_count: int | None = None,
    text_p1_3: str | None = None,
) -> str:
    _table(doc_class)  # walidacja klasy
    touch = dict(
        doc_class=doc_class, job_id=job_id, source_name=source_name,
        pdf_sha256=pdf_sha256, pdf_path=pdf_path, page_count=page_count,
        text_p1_3=text_p1_3,
    )

    # Fast path: the unique (client_token, client_doc_id) index makes this a
    # single atomic INSERT. No check-then-write race between clients.
    if client_doc_id is not None and client_token is not None:
        doc_id = _new_id()
        cur = conn.execute(
            """INSERT OR IGNORE INTO source_documents
               (id, job_id, client_token, client_doc_id, doc_class, source_name,
                pdf_sha256, pdf_path, page_count, text_p1_3, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (doc_id, job_id, client_token, client_doc_id, doc_class, source_name,
             pdf_sha256, pdf_path, page_count, text_p1_3, _now()),
        )
        if cur.rowcount == 0:
            row = conn.execute(
                """SELECT id FROM source_documents
                   WHERE client_token = ? AND client_doc_id = ?""",
                (client_token, client_doc_id),
            ).fetchone()
            doc_id = row["id"]
            _touch_source_document(conn, doc_id, **touch)
        return doc_id

    # Legacy path (no token or no client_doc_id): no unique constraint, so a
    # lookup is unavoidable. Same key wins; a different token stays separate.
    existing = _find_keyed_document(conn, client_token, client_doc_id)
    if existing is None and client_token and client_doc_id is None:
        existing = conn.execute(
            """SELECT id FROM source_documents
               WHERE client_token = ? AND doc_class = ?""",
            (client_token, doc_class),
        ).fetchone()
    if existing is not None:
        _touch_source_document(conn, existing["id"], **touch)
        return existing["id"]

    doc_id = _new_id()
    conn.execute(
        """INSERT INTO source_documents
           (id, job_id, client_token, client_doc_id, doc_class, source_name,
            pdf_sha256, pdf_path, page_count, text_p1_3, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (doc_id, job_id, client_token, client_doc_id, doc_class, source_name,
         pdf_sha256, pdf_path, page_count, text_p1_3, _now()),
    )
    return doc_id


def _reset_for_class_change(
    conn: sqlite3.Connection, document_id: str, old_class: str
) -> None:
    """A reclassify invalidates the old class's result and its corrections.

    Correction snapshots describe the old schema; carrying them into a new
    class table would mix two shapes in one effective JSON.
    """
    conn.execute(
        f"DELETE FROM {_table(old_class)} WHERE document_id = ?", (document_id,)
    )
    conn.execute("DELETE FROM correction_sessions WHERE document_id = ?", (document_id,))


def get_source_document(conn: sqlite3.Connection, document_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM source_documents WHERE id = ?", (document_id,)).fetchone()
    return dict(row) if row else None


def list_source_documents(
    conn: sqlite3.Connection,
    *,
    job_id: str | None = None,
    doc_class: str | None = None,
    client_token: str | None = None,
) -> list[dict[str, Any]]:
    query = "SELECT * FROM source_documents WHERE 1=1"
    params: list[Any] = []
    for col, val in (("job_id", job_id), ("doc_class", doc_class), ("client_token", client_token)):
        if val is not None:
            query += f" AND {col} = ?"
            params.append(val)
    query += " ORDER BY created_at ASC, rowid ASC"
    return [dict(r) for r in conn.execute(query, params).fetchall()]


# ---------------------------------------------------------------------------
# Magazyny 1-3: wyniki modelu (nienaruszalne)
# ---------------------------------------------------------------------------


def save_result(
    conn: sqlite3.Connection,
    *,
    doc_class: str,
    document_id: str,
    canonical_json: dict[str, Any],
    provenance_json: dict[str, Any] | None = None,
    model_version: str | None = None,
    config_version: str | None = None,
) -> bool:
    """Zapisz wynik do właściwego magazynu. Zwraca False, gdy już istnieje
    (wynik modelu nie jest nadpisywany)."""
    table = _table(doc_class)
    doc = get_source_document(conn, document_id)
    if doc is not None and doc["doc_class"] != doc_class:
        raise ValueError(
            f"doc_class mismatch for {document_id!r}: document is "
            f"{doc['doc_class']!r}, not {doc_class!r}"
        )
    # INSERT OR IGNORE + rowcount replaces the racy check-then-write. The
    # document_id is the primary key, so a repeat ingest is silently ignored.
    cur = conn.execute(
        f"""INSERT OR IGNORE INTO {table}
            (document_id, canonical_json, provenance_json, model_version,
             config_version, created_at)
            VALUES (?, ?, ?, ?, ?, ?)""",
        (document_id, _dumps(canonical_json),
         _dumps(provenance_json) if provenance_json is not None else None,
         model_version, config_version, _now()),
    )
    created = cur.rowcount > 0
    # SELECT confirms the row the caller will read back is the one we kept.
    conn.execute(f"SELECT 1 FROM {table} WHERE document_id = ?", (document_id,)).fetchone()
    return created


def get_result(conn: sqlite3.Connection, doc_class: str, document_id: str) -> dict[str, Any] | None:
    table = _table(doc_class)
    row = conn.execute(
        f"SELECT * FROM {table} WHERE document_id = ?", (document_id,)
    ).fetchone()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# Magazyn 4: poprawki
# ---------------------------------------------------------------------------


def create_correction_session(
    conn: sqlite3.Connection,
    *,
    document_id: str,
    predicted: dict[str, Any],
    corrected: dict[str, Any],
    reviewer: str | None = None,
    text_p1_3: str | None = None,
    method_by_path: dict[str, str] | None = None,
    model_version: str | None = None,
    config_version: str | None = None,
) -> str:
    """Zapisz parę (źle odczytany JSON, poprawiony JSON) + różnice per pole."""
    session_id = _new_id()
    conn.execute(
        """INSERT INTO correction_sessions
           (id, document_id, predicted_json, corrected_json, reviewer, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (session_id, document_id, _dumps(predicted), _dumps(corrected), reviewer, _now()),
    )
    method_by_path = method_by_path or {}
    for field_path, pred_val, corr_val in diff_json(predicted, corrected):
        meta = method_by_path.get(field_path) or method_by_path.get(
            re.sub(r"\[\d+\]", "[]", field_path), {}
        )
        if isinstance(meta, dict):
            method = meta.get("method")
            confidence = meta.get("confidence")
            page = meta.get("page")
            bbox = _dumps(meta["bbox"]) if meta.get("bbox") is not None else None
            quote = meta.get("quote")
        else:
            method, confidence, page, bbox, quote = meta, None, None, None, None
        conn.execute(
            """INSERT INTO correction_items
               (session_id, field_path, predicted_value, corrected_value,
                method, confidence, page, bbox, quote,
                validator_ok, grounded_ok, model_version, config_version)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (session_id, field_path,
             _as_text(pred_val), _as_text(corr_val),
             method, confidence, page, bbox, quote,
             int(validator_ok(field_path, corr_val)),
             grounded_ok(field_path, corr_val, text_p1_3),
             model_version, config_version),
        )
    return session_id


def _latest_effective_json(conn: sqlite3.Connection, document_id: str, fallback: str) -> str:
    """Latest corrected snapshot, or the pristine model output when none exists."""
    row = conn.execute(
        """SELECT corrected_json FROM correction_sessions WHERE document_id = ?
           ORDER BY created_at DESC, rowid DESC LIMIT 1""",
        (document_id,),
    ).fetchone()
    return row["corrected_json"] if row else fallback


def save_corrections(
    conn: sqlite3.Connection,
    *,
    document_id: str,
    items: list[dict[str, Any]],
    reviewer: str | None = None,
    model_version: str | None = None,
    config_version: str | None = None,
) -> str:
    """Dodaj poprawki per pole do magazynu 4 (bez zmiany magazynu 1-3)."""
    # The whole read-modify-write runs under one write lock. Two reviewers
    # editing different fields must stack, not overwrite each other.
    with _immediate(conn):
        doc = get_source_document(conn, document_id)
        if doc is None:
            raise ValueError(f"unknown document_id {document_id!r}")
        result = get_result(conn, doc["doc_class"], document_id)
        if result is None:
            raise ValueError(f"document {document_id!r} has no stored result")

        base_json = _latest_effective_json(
            conn, document_id, result["canonical_json"]
        )
        # predicted_value = the value the user is currently correcting (current
        # effective value), NOT the pristine output, so training pairs reflect
        # what was actually on screen. Stores 1-3 stay immutable;
        # get_effective_result()["predicted_json"] returns the original output.
        predicted = json.loads(base_json)
        corrected = json.loads(base_json)
        method_by_path: dict[str, Any] = {}
        provenance = json.loads(result["provenance_json"]) if result["provenance_json"] else {}
        if isinstance(provenance, dict):
            method_by_path = provenance.get("fields", provenance)

        for item in items:
            path = item["field_path"]
            set_by_path(corrected, path, item.get("corrected_value"))
            if item.get("method") or item.get("confidence") is not None:
                method_by_path[path] = {k: item[k] for k in
                                        ("method", "confidence", "page", "bbox", "quote")
                                        if k in item}

        return create_correction_session(
            conn,
            document_id=document_id,
            predicted=predicted,
            corrected=corrected,
            reviewer=reviewer,
            text_p1_3=doc.get("text_p1_3"),
            method_by_path=method_by_path,
            model_version=model_version,
            config_version=config_version,
        )


def ingest_document(
    conn: sqlite3.Connection,
    *,
    client_token: str,
    client_doc_id: str | None = None,
    doc_class: str,
    canonical_json: dict[str, Any],
    provenance_json: dict[str, Any] | None = None,
    source_name: str | None = None,
    pdf_sha256: str | None = None,
    text_p1_3: str | None = None,
    model_version: str | None = None,
    config_version: str | None = None,
    reviewer: str | None = None,
) -> dict[str, Any]:
    """Jednopunktowy zapis z frontendu.

    Pierwszy zapis dla client_doc_id (jednego pliku z ZIP-a) tworzy dokument
    i wynik w magazynie 1/2/3. Kolejne zapisy tego samego pliku z inną treścią
    jsona NIE nadpisują wyniku — tworzą sesję poprawki w magazynie 4.

    client_doc_id pozwala mieć w jednej sprawie wiele dokumentów tego samego
    typu (np. 3 przelewy i 2 odwołania).
    """
    if not isinstance(canonical_json, dict):
        raise ValueError("canonical_json must be an object")

    # Capture the old class before upsert (which now refreshes doc_class).
    old = _find_keyed_document(conn, client_token, client_doc_id)
    doc_id = upsert_source_document(
        conn,
        doc_class=doc_class,
        client_token=client_token,
        client_doc_id=client_doc_id,
        source_name=source_name,
        pdf_sha256=pdf_sha256,
        text_p1_3=text_p1_3,
    )
    if old is not None and old["doc_class"] != doc_class:
        _reset_for_class_change(conn, doc_id, old["doc_class"])

    created = save_result(
        conn,
        doc_class=doc_class,
        document_id=doc_id,
        canonical_json=canonical_json,
        provenance_json=provenance_json,
        model_version=model_version,
        config_version=config_version,
    )
    session_id = None
    if not created:
        stored = get_result(conn, doc_class, doc_id)
        pristine = json.loads(stored["canonical_json"])
        # Only the fields the new model output actually changed get applied.
        # Re-applying the whole submission would silently revert corrections
        # on fields the caller did not touch.
        model_diff = diff_json(pristine, canonical_json)
        if model_diff:
            base = json.loads(_latest_effective_json(
                conn, doc_id, stored["canonical_json"]
            ))
            corrected = json.loads(_dumps(base))
            for path, _old_value, new_value in model_diff:
                set_by_path(corrected, path, new_value)
            source_doc = get_source_document(conn, doc_id)
            session_id = create_correction_session(
                conn,
                document_id=doc_id,
                predicted=base,
                corrected=corrected,
                reviewer=reviewer,
                text_p1_3=text_p1_3 or (source_doc or {}).get("text_p1_3"),
                model_version=model_version,
                config_version=config_version,
            )
    return {
        "document_id": doc_id,
        "client_doc_id": client_doc_id,
        "doc_class": doc_class,
        "created": created,
        "correction_session_id": session_id,
    }


# ---------------------------------------------------------------------------
# Odczyt „effective JSON" (wynik + nałożone poprawki)
# ---------------------------------------------------------------------------


def get_effective_result(conn: sqlite3.Connection, document_id: str) -> dict[str, Any] | None:
    doc = get_source_document(conn, document_id)
    if doc is None:
        return None
    result = get_result(conn, doc["doc_class"], document_id)
    if result is None:
        return None
    sessions = conn.execute(
        """SELECT * FROM correction_sessions WHERE document_id = ?
           ORDER BY created_at DESC, rowid DESC""",
        (document_id,),
    ).fetchall()
    effective = json.loads(result["canonical_json"])
    if sessions:
        effective = json.loads(sessions[0]["corrected_json"])
    return {
        "document_id": document_id,
        "client_doc_id": doc.get("client_doc_id"),
        "doc_class": doc["doc_class"],
        "source_name": doc.get("source_name"),
        "job_id": doc.get("job_id"),
        "canonical_json": effective,
        "predicted_json": json.loads(result["canonical_json"]),
        "provenance_json": json.loads(result["provenance_json"]) if result["provenance_json"] else None,
        "model_version": result.get("model_version"),
        "config_version": result.get("config_version"),
        "correction_count": len(sessions),
        "latest_correction_session_id": sessions[0]["id"] if sessions else None,
        "created_at": result.get("created_at"),
    }


def list_effective_results(
    conn: sqlite3.Connection,
    *,
    job_id: str | None = None,
    doc_class: str | None = None,
    client_token: str | None = None,
) -> list[dict[str, Any]]:
    docs = list_source_documents(conn, job_id=job_id, doc_class=doc_class,
                                 client_token=client_token)
    out = []
    for doc in docs:
        effective = get_effective_result(conn, doc["id"])
        if effective is not None:
            out.append(effective)
    return out


def get_correction_items(conn: sqlite3.Connection, session_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM correction_items WHERE session_id = ? ORDER BY id", (session_id,)
    ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Eksport par treningowych (tylko CLI — brak endpointu API)
# ---------------------------------------------------------------------------


def export_training_pairs(
    conn: sqlite3.Connection,
    *,
    doc_class: str | None = None,
    only_clean: bool = True,
) -> list[dict[str, Any]]:
    """Pary (tekst źródłowy -> poprawiony JSON) do douczania modelu.

    only_clean=True odrzuca sesje, w których choć jedno pole nie przeszło
    sumy kontrolnej albo nie zostało ugruntowane w tekście.
    """
    query = """
        SELECT cs.id AS session_id, d.doc_class, d.text_p1_3, cs.corrected_json,
               COUNT(ci.id) AS n_items,
               SUM(CASE WHEN ci.validator_ok = 0 OR ci.grounded_ok = 0
                        THEN 1 ELSE 0 END) AS bad_items
        FROM correction_sessions cs
        JOIN source_documents d ON d.id = cs.document_id
        LEFT JOIN correction_items ci ON ci.session_id = cs.id
        WHERE 1 = 1
    """
    params: list[Any] = []
    if doc_class is not None:
        _table(doc_class)
        query += " AND d.doc_class = ?"
        params.append(doc_class)
    query += " GROUP BY cs.id"
    if only_clean:
        query += " HAVING COALESCE(bad_items, 0) = 0"
    query += " ORDER BY cs.created_at ASC, cs.rowid ASC"

    out = []
    for row in conn.execute(query, params).fetchall():
        out.append({
            "session_id": row["session_id"],
            "doc_class": row["doc_class"],
            "text_p1_3": row["text_p1_3"],
            "corrected_json": json.loads(row["corrected_json"]),
            "n_items": row["n_items"],
            "grounded": None if not row["text_p1_3"] else True,
        })
    return out

