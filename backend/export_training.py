"""Eksport par treningowych do JSONL — TYLKO lokalne CLI, bez endpointu API.

Użycie:
    PYTHONPATH=src:. python -m backend.export_training --out work/pary.jsonl
    PYTHONPATH=src:. python -m backend.export_training --class przelew --out ...

Domyślnie eksportuje tylko „czyste" sesje: wszystkie poprawione pola
przeszły sumę kontrolną i (jeśli był dostępny tekst) zostały ugruntowane.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from backend.db import repository as repo
from backend.db.connection import db


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Eksport par tekst -> poprawiony JSON")
    parser.add_argument("--class", dest="doc_class", choices=sorted(repo.CLASS_TO_TABLE))
    parser.add_argument("--out", type=Path, help="Plik JSONL (domyślnie stdout)")
    parser.add_argument(
        "--include-unverified",
        action="store_true",
        help="Eksportuj też poprawki, które nie przeszły sumy kontrolnej / groundingu",
    )
    args = parser.parse_args(argv)

    with db() as conn:
        pairs = repo.export_training_pairs(
            conn, doc_class=args.doc_class, only_clean=not args.include_unverified
        )

    lines = [json.dumps(p, ensure_ascii=False) for p in pairs]
    payload = "\n".join(lines) + ("\n" if lines else "")
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(payload, encoding="utf-8")
        print(f"Zapisano {len(pairs)} par do {args.out}", file=sys.stderr)
    else:
        sys.stdout.write(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
