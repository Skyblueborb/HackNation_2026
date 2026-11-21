"""Testy warstwy SQLite backendu: cztery magazyny JSON, niezmienność wyniku
modelu, poprawki jako overlay i eksport par treningowych.

Uruchamianie (wymaga PYTHONPATH z src/):
    PYTHONPATH=src:. .venv/bin/python -m pytest tests/test_backend_db.py -q
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from backend.db import repository as repo
from backend.db.connection import connect, db, init_db

GOOD_NIP = "5260001246"
BAD_NIP = "5260001247"
UZP_ACCOUNT = "60101010100081362231000000"


def _base_payload() -> dict:
    return {
        "OdwolanieKIO": {
            "data": "2025-10-13",
            "czynnosc_dzien": "2025-10-01",
            "czynnosc_powod_id": 4,
            "czynnosc_opis": "Publikacja SWZ",
            "miejscowosc": "Pruszków",
        },
        "Odwolujacy": [{
            "krs": "0000054580", "nazwa": "STRABAG Sp. z o.o.",
            "nip": GOOD_NIP, "regon": None, "przez-pelnomocnika": 1,
            "pelnomocnik": None,
        }],
        "Zamawiajacy": [{
            "krs": None, "nazwa": "Filharmonia Pomorska",
            "nip": "5540240549", "regon": None, "prowadzacy_postepowanie": None,
        }],
        "ZamowieniePubliczne": {
            "numer_bzp": None, "numer_postepowania": "ZP.039.2025",
            "numer_ted": "641651-2025", "tytul": "Przebudowa filharmonii",
        },
    }


# --- schemat ---------------------------------------------------------------


def test_schema_contains_four_separate_json_stores(tmp_path):
    path = init_db(tmp_path / "o2j.db")
    conn = connect(path)
    try:
        names = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
    finally:
        conn.close()
    assert {
        "json_odwolanie",
        "json_pelnomocnictwo",
        "json_przelew",
        "correction_sessions",
        "correction_items",
        "jobs",
        "source_documents",
    } <= names


def test_sqlite_json_constraint_rejects_invalid_json(tmp_path):
    path = init_db(tmp_path / "o2j.db")
    conn = connect(path)
    try:
        with pytest.raises(Exception):
            conn.execute(
                "INSERT INTO json_przelew (document_id, canonical_json, created_at) "
                "VALUES ('x', 'not json', 'now')"
            )
    finally:
        conn.close()


# --- ścieżki pól -----------------------------------------------------------


def test_set_by_path_handles_nested_lists_and_empty_index():
    obj: dict = {}
    repo.set_by_path(obj, "mocodawca[].podpisujacy[].imie_nazwisko", "Jan Kowalski")
    assert obj == {"mocodawca": [{"podpisujacy": [{"imie_nazwisko": "Jan Kowalski"}]}]}
    repo.set_by_path(obj, "Odwolujacy[0].nip", "1234567890")
    assert obj["Odwolujacy"][0]["nip"] == "1234567890"


def test_diff_json_reports_changed_leaf_with_indexed_path():
    diffs = repo.diff_json({"Odwolujacy": [{"nip": GOOD_NIP}]},
                           {"Odwolujacy": [{"nip": BAD_NIP}]})
    assert diffs == [("Odwolujacy[0].nip", GOOD_NIP, BAD_NIP)]


# --- magazyny 1-3 i magazyn 4 ----------------------------------------------


def test_first_ingest_creates_result_second_ingest_creates_correction(tmp_path):
    init_db(tmp_path / "o2j.db")
    changed = _base_payload()
    changed["Odwolujacy"][0]["nip"] = BAD_NIP

    with db(tmp_path / "o2j.db") as conn:
        first = repo.ingest_document(conn, client_token="tab-1", doc_class="odwolanie",
                                     canonical_json=_base_payload())
        assert first["created"] is True and first["correction_session_id"] is None
        doc_id = first["document_id"]

        second = repo.ingest_document(conn, client_token="tab-1", doc_class="odwolanie",
                                      canonical_json=changed)
        assert second["document_id"] == doc_id
        assert second["created"] is False
        assert second["correction_session_id"] is not None
        items = repo.get_correction_items(conn, second["correction_session_id"])
        assert [i["field_path"] for i in items] == ["Odwolujacy[0].nip"]
        assert items[0]["predicted_value"] == GOOD_NIP
        assert items[0]["corrected_value"] == BAD_NIP


def test_result_store_is_immutable_but_effective_json_is_corrected(tmp_path):
    init_db(tmp_path / "o2j.db")
    changed = _base_payload()
    changed["Odwolujacy"][0]["nazwa"] = "POPRAWIONA NAZWA"

    with db(tmp_path / "o2j.db") as conn:
        first = repo.ingest_document(conn, client_token="tab-2", doc_class="odwolanie",
                                     canonical_json=_base_payload())
        doc_id = first["document_id"]
        repo.save_corrections(conn, document_id=doc_id,
                              items=[{"field_path": "Odwolujacy[0].nazwa",
                                      "corrected_value": "POPRAWIONA NAZWA"}])

        stored = repo.get_result(conn, "odwolanie", doc_id)
        assert json.loads(stored["canonical_json"])["Odwolujacy"][0]["nazwa"] == "STRABAG Sp. z o.o."

        effective = repo.get_effective_result(conn, doc_id)
        assert effective["canonical_json"]["Odwolujacy"][0]["nazwa"] == "POPRAWIONA NAZWA"
        assert effective["predicted_json"]["Odwolujacy"][0]["nazwa"] == "STRABAG Sp. z o.o."
        assert effective["correction_count"] == 1


def test_sequential_correction_sessions_preserve_earlier_fixes(tmp_path):
    """Druga sesja poprawiająca inne pole nie cofa poprawki z pierwszej sesji."""
    init_db(tmp_path / "o2j.db")
    original = _base_payload()
    with db(tmp_path / "o2j.db") as conn:
        first = repo.ingest_document(conn, client_token="tab-seq", doc_class="odwolanie",
                                     canonical_json=original)
        doc_id = first["document_id"]

        repo.save_corrections(conn, document_id=doc_id,
                              items=[{"field_path": "Odwolujacy[0].nazwa",
                                      "corrected_value": "POPRAWIONA NAZWA"}])
        repo.save_corrections(conn, document_id=doc_id,
                              items=[{"field_path": "Odwolujacy[0].nip",
                                      "corrected_value": BAD_NIP}])

        effective = repo.get_effective_result(conn, doc_id)
        assert effective["canonical_json"]["Odwolujacy"][0]["nazwa"] == "POPRAWIONA NAZWA"
        assert effective["canonical_json"]["Odwolujacy"][0]["nip"] == BAD_NIP
        assert effective["correction_count"] == 2
        # predicted_json pozostaje oryginalnym wynikiem modelu (magazyn 1-3).
        assert effective["predicted_json"]["Odwolujacy"][0]["nazwa"] == "STRABAG Sp. z o.o."
        assert effective["predicted_json"]["Odwolujacy"][0]["nip"] == GOOD_NIP


def test_three_classes_are_stored_in_three_different_tables(tmp_path):
    init_db(tmp_path / "o2j.db")
    with db(tmp_path / "o2j.db") as conn:
        a = repo.ingest_document(conn, client_token="t", doc_class="odwolanie",
                                 canonical_json=_base_payload())
        p = repo.ingest_document(conn, client_token="t", doc_class="pelnomocnictwo",
                                 canonical_json={"mocodawca": [], "pelnomocnicy": []})
        r = repo.ingest_document(conn, client_token="t", doc_class="przelew",
                                 canonical_json={"przelew_bankowy": {"kwota": 10000.0}})

    with connect(tmp_path / "o2j.db") as conn:
        for table, doc_id in (("json_odwolanie", a["document_id"]),
                              ("json_pelnomocnictwo", p["document_id"]),
                              ("json_przelew", r["document_id"])):
            assert conn.execute(
                f"SELECT 1 FROM {table} WHERE document_id = ?", (doc_id,)
            ).fetchone() is not None


def test_multiple_files_of_same_class_are_independent_documents(tmp_path):
    """3 przelewy w jednym ZIP-ie to 3 osobne byty, nie poprawki jednego."""
    init_db(tmp_path / "o2j.db")
    with db(tmp_path / "o2j.db") as conn:
        results = []
        for i, kwota in enumerate((10000.0, 15000.0, 20000.0), start=1):
            results.append(repo.ingest_document(
                conn, client_token="jeden-zip", client_doc_id=f"plik-{i}",
                doc_class="przelew",
                canonical_json={"przelew_bankowy": {"kwota": kwota}},
            ))

        assert len({r["document_id"] for r in results}) == 3
        assert all(r["created"] for r in results)
        assert all(r["correction_session_id"] is None for r in results)

        docs = repo.list_source_documents(conn, client_token="jeden-zip")
        assert [d["client_doc_id"] for d in docs] == ["plik-1", "plik-2", "plik-3"]

        effective = repo.list_effective_results(conn, client_token="jeden-zip")
        assert [r["canonical_json"]["przelew_bankowy"]["kwota"] for r in effective] == [
            10000.0, 15000.0, 20000.0
        ]


def test_unknown_doc_class_is_rejected(tmp_path):
    init_db(tmp_path / "o2j.db")
    with db(tmp_path / "o2j.db") as conn, pytest.raises(ValueError):
        repo.ingest_document(conn, client_token="t", doc_class="faktura", canonical_json={})


# --- flagi jakości i eksport treningowy -------------------------------------


def test_checksum_and_grounding_flags(tmp_path):
    init_db(tmp_path / "o2j.db")
    text = f"NIP odwołującego: {GOOD_NIP}. Postępowanie ZP.039.2025."
    with db(tmp_path / "o2j.db") as conn:
        first = repo.ingest_document(
            conn, client_token="t", doc_class="odwolanie",
            canonical_json=_base_payload(), text_p1_3=text,
        )
        # poprawka na NIP z błędną sumą kontrolną
        bad = repo.save_corrections(conn, document_id=first["document_id"],
                                    items=[{"field_path": "Odwolujacy[0].nip",
                                            "corrected_value": BAD_NIP}])
        bad_items = repo.get_correction_items(conn, bad)
        assert bad_items[0]["validator_ok"] == 0
        assert bad_items[0]["grounded_ok"] == 0

        # poprawka na NIP z poprawną sumą kontrolną (inny niż oryginał)
        good_nip_2 = "5260001246"  # ten sam co oryginał -> zmieniamy nazwę zamiast tego
        good = repo.save_corrections(
            conn, document_id=first["document_id"],
            items=[{"field_path": "Odwolujacy[0].nazwa", "corrected_value": "NOWA NAZWA"}],
        )
        good_items = repo.get_correction_items(conn, good)
        assert good_items[0]["validator_ok"] == 1  # pole bez sumy kontrolnej
        assert good_items[0]["grounded_ok"] == 0   # "NOWA NAZWA" nie ma w tekście
        assert good_nip_2 == GOOD_NIP


def test_export_training_pairs_filters_sessions_with_bad_items(tmp_path):
    init_db(tmp_path / "o2j.db")
    text = "NIP: 5260001246, nazwa: NOWY PODMIOT"
    with db(tmp_path / "o2j.db") as conn:
        first = repo.ingest_document(
            conn, client_token="t", doc_class="odwolanie",
            canonical_json=_base_payload(), text_p1_3=text,
        )
        clean = repo.save_corrections(
            conn, document_id=first["document_id"],
            items=[{"field_path": "Odwolujacy[0].nazwa", "corrected_value": "NOWY PODMIOT"}],
        )
        dirty = repo.save_corrections(
            conn, document_id=first["document_id"],
            items=[{"field_path": "Odwolujacy[0].nip", "corrected_value": BAD_NIP}],
        )
        clean_pairs = repo.export_training_pairs(conn)
        assert [p["session_id"] for p in clean_pairs] == [clean]

        all_pairs = repo.export_training_pairs(conn, only_clean=False)
        assert {p["session_id"] for p in all_pairs} == {clean, dirty}
        assert all_pairs[0]["corrected_json"]["Odwolujacy"][0]["nazwa"] == "NOWY PODMIOT"


# --- API -------------------------------------------------------------------


def test_api_health_and_ingest(tmp_path, monkeypatch):
    monkeypatch.setenv("O2J_DB_PATH", str(tmp_path / "api.db"))
    monkeypatch.delenv("API_TOKEN", raising=False)
    monkeypatch.delenv("O2J_STRICT_VALIDATION", raising=False)

    from backend.main import app

    with TestClient(app) as client:
        assert client.get("/api/health").json()["status"] == "ok"
        resp = client.post("/api/documents/ingest", json={
            "client_token": "api-tab", "doc_class": "przelew",
            "canonical_json": {"przelew_bankowy": {"kwota": 15000.0,
                                                   "na_rachunek": UZP_ACCOUNT}},
        })
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["created"] is True

        docs = client.get("/api/documents", params={"client_token": "api-tab"}).json()
        assert len(docs) == 1
        assert docs[0]["canonical_json"]["przelew_bankowy"]["kwota"] == 15000.0

        patched = client.patch(
            f"/api/documents/{body['document_id']}/corrections",
            json={"items": [{"field_path": "przelew_bankowy.kwota",
                             "corrected_value": 10000.0}]},
        )
        assert patched.status_code == 200, patched.text
        assert patched.json()["correction_session_id"]


def test_api_requires_token_when_configured(tmp_path, monkeypatch):
    monkeypatch.setenv("O2J_DB_PATH", str(tmp_path / "token.db"))
    monkeypatch.setenv("API_TOKEN", "sekret")
    from backend.main import app

    with TestClient(app) as client:
        assert client.get("/api/documents").status_code == 401
        assert client.get("/api/documents", headers={"X-API-Token": "sekret"}).status_code == 200
