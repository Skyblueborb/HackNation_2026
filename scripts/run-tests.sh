#!/usr/bin/env bash
# =============================================================================
# run-tests.sh — Przetwórz N przykładów przez backend i porównaj z oczekiwanym JSON.
#
# Użycie:
#   bash scripts/run-tests.sh 5                           # 5 przykładów, domyślny backend
#   bash scripts/run-tests.sh 3 http://192.168.1.220:8000 # 3 przykłady, zdalny backend
#   bash scripts/run-tests.sh 60                           # wszystkie 60
#
# Wymagania:
#   - Backend musi być uruchomiony (lokalnie lub zdalnie).
#   - uv zainstalowane i skonfigurowane.
#
# Co robi:
#   1. Dla N pierwszych przykładów przetwarza 3 PDF-y (odwołanie, pełnomocnictwo, przelew)
#      przez `uv run ocr-pdf2json --remote <backend>`.
#   2. Wyniki trafiają do pdfy/output_nasz/przyklad_NN/.
#   3. Porównuje output_nasz z output (wzorcowe JSON-y) używając ewaluatora lab.
#   4. Wypisuje raport: F1 exact/fuzzy, per-class, per-file.
# =============================================================================

set -euo pipefail
cd "$(dirname "$0")/.."

N="${1:-5}"
BACKEND="${2:-http://localhost:8000}"
API_TOKEN="${O2J_API_TOKEN:-${API_TOKEN:-}}"

# Dane konkursowe leżą w osobnym repo: <data_root>/dane/przyklad_*/...
DATA_ROOT="${O2J_DATA_ROOT:-../dane/hacknation-2026}"
INPUT_DIR="$DATA_ROOT/dane"
GOLD_DIR="$DATA_ROOT/dane"
OUR_DIR="${O2J_WORK_ROOT:-work}/pipeline-tests"

# Kolory do terminala
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m'

echo -e "${BOLD}╔══════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║       Odwołania2json — Test Pipeline                ║${NC}"
echo -e "${BOLD}╠══════════════════════════════════════════════════════╣${NC}"
echo -e "${BOLD}║${NC} Backend:   ${BLUE}${BACKEND}${NC}"
echo -e "${BOLD}║${NC} Przykłady: ${BLUE}${N}${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════════════════╝${NC}"
echo ""

# Sprawdź czy backend żyje
if ! curl -fsS -o /dev/null "${BACKEND}/api/health" 2>/dev/null; then
  if curl -fsS -o /dev/null "${BACKEND}/api/health" 2>/dev/null || [ $? -eq 22 ]; then
    : # 401/403 = żyje, wymaga tokenu
  else
    echo -e "${RED}✗ Backend nie odpowiada na ${BACKEND}/api/health${NC}"
    echo "  Uruchom: bash scripts/dev-up.sh"
    exit 1
  fi
fi
echo -e "${GREEN}✓ Backend dostępny${NC}"
echo ""

# Mapowanie: nazwa PDF -> nazwa gold JSON
# ocr-pdf2json zapisuje <pdf_stem>.json, ale gold zawsze to:
#   odwolanie.pdf          -> odwolanie.json    ✓
#   pelnomocnictwo.pdf     -> pelnomocnictwo.json ✓
#   potwierdzenie_przelewu.pdf -> potwierdzenie_przelewu.json ✗ (gold = przelew.json)
#   przelew.pdf            -> przelew.json      ✓

# Zbierz posortowane przykłady
EXAMPLES=($(ls -d "$INPUT_DIR"/przyklad_* 2>/dev/null | sort -t_ -k2 -n | head -n "$N"))

if [ ${#EXAMPLES[@]} -eq 0 ]; then
  echo -e "${RED}✗ Brak przykładów w ${INPUT_DIR}${NC}"
  exit 1
fi

echo -e "${BOLD}Przetwarzanie ${#EXAMPLES[@]} przykładów...${NC}"
echo ""

TOTAL_PDFS=0
OK_PDFS=0
FAIL_PDFS=0
SKIP_PDFS=0

TOKEN_ARGS=""
if [ -n "$API_TOKEN" ]; then
  TOKEN_ARGS="--api-token $API_TOKEN"
fi

for example_dir in "${EXAMPLES[@]}"; do
  example=$(basename "$example_dir")
  num="${example#przyklad_}"
  out_dir="${OUR_DIR}/${example}"
  mkdir -p "$out_dir"

  echo -e "${BOLD}── ${example} ──${NC}"

  # Przetwórz każdy z 3 typów dokumentów
  for doc_type in odwolanie pelnomocnictwo przelew; do
    # Znajdź odpowiedni PDF
    pdf_path=""
    if [ "$doc_type" = "przelew" ]; then
      # Szukaj: przelew.pdf lub potwierdzenie_przelewu.pdf
      if [ -f "${example_dir}/przelew.pdf" ]; then
        pdf_path="${example_dir}/przelew.pdf"
      elif [ -f "${example_dir}/potwierdzenie_przelewu.pdf" ]; then
        pdf_path="${example_dir}/potwierdzenie_przelewu.pdf"
      fi
    else
      pdf_path="${example_dir}/${doc_type}.pdf"
    fi

    if [ -z "$pdf_path" ] || [ ! -f "$pdf_path" ]; then
      echo -e "  ${YELLOW}⊘ ${doc_type}: brak PDF — pomijam${NC}"
      ((SKIP_PDFS++)) || true
      continue
    fi

    ((TOTAL_PDFS++)) || true

    # Uruchom ocr-pdf2json z trybem remote
    tmp_out=$(mktemp -d)
    if uv run ocr-pdf2json "$pdf_path" \
         --remote "$BACKEND" \
         --doc-class "$doc_type" \
         --out-dir "$tmp_out" \
         $TOKEN_ARGS \
         2>/dev/null; then

      # Przekopiuj wynik z właściwą nazwą (gold_stem)
      # ocr-pdf2json zapisuje <basename>.json, musimy zmapować na gold_stem
      generated=$(ls "$tmp_out"/*.json 2>/dev/null | head -1)
      if [ -n "$generated" ]; then
        gold_name="${doc_type}.json"
        cp "$generated" "${out_dir}/${gold_name}"
        echo -e "  ${GREEN}✓ ${doc_type}${NC} → ${out_dir}/${gold_name}"
        ((OK_PDFS++)) || true
      else
        echo -e "  ${RED}✗ ${doc_type}: brak wyniku JSON${NC}"
        ((FAIL_PDFS++)) || true
      fi
    else
      echo -e "  ${RED}✗ ${doc_type}: błąd przetwarzania${NC}"
      ((FAIL_PDFS++)) || true
    fi

    rm -rf "$tmp_out"
  done
  echo ""
done

echo -e "${BOLD}╔══════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║                  Podsumowanie ekstrakcji            ║${NC}"
echo -e "${BOLD}╠══════════════════════════════════════════════════════╣${NC}"
echo -e "${BOLD}║${NC} Przetworzone:   ${GREEN}${OK_PDFS}${NC} / ${TOTAL_PDFS}"
echo -e "${BOLD}║${NC} Błędy:          ${RED}${FAIL_PDFS}${NC}"
echo -e "${BOLD}║${NC} Pominięte:      ${YELLOW}${SKIP_PDFS}${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════════════════╝${NC}"
echo ""

# --- Faza 2: Porównanie z goldem ---

echo -e "${BOLD}═══════════════════════════════════════════════════════${NC}"
echo -e "${BOLD}  Ewaluacja: output_nasz vs output (gold)             ${NC}"
echo -e "${BOLD}═══════════════════════════════════════════════════════${NC}"
echo ""

# Użyj wbudowanego ewaluatora lab
export PYTHONPATH="src:."
uv run python - "$OUR_DIR" "$GOLD_DIR" "$N" <<'PYEOF'
import json
import sys
from pathlib import Path
from rapidfuzz import fuzz

pred_root = Path(sys.argv[1])
gold_root = Path(sys.argv[2])
n = int(sys.argv[3])

DOC_TYPES = ["odwolanie", "pelnomocnictwo", "przelew"]

class Counts:
    def __init__(self):
        self.tp = self.fp = self.fn = self.tn = 0

    @property
    def precision(self):
        d = self.tp + self.fp
        return self.tp / d if d else (1.0 if self.fn == 0 else 0.0)

    @property
    def recall(self):
        d = self.tp + self.fn
        return self.tp / d if d else (1.0 if self.fp == 0 else 0.0)

    @property
    def f1(self):
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0


def flatten(obj, prefix=""):
    """Spłaszcza zagnieżdżony JSON do ścieżek kropkowych."""
    out = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            flatten(v, f"{prefix}{k}." if prefix else f"{k}.", out=out)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            flatten(v, f"{prefix}[{i}].", out=out)
    else:
        key = prefix.rstrip(".")
        out[key] = obj
    return out


def flatten(obj, prefix="", out=None):
    if out is None:
        out = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            flatten(v, f"{prefix}{k}.", out)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            flatten(v, f"{prefix}[{i}].", out)
    else:
        key = prefix.rstrip(".")
        out[key] = obj
    return out


def compare_values(pred, gold, fuzzy_threshold=90):
    """Zwraca (exact_verdict, fuzzy_verdict)."""
    if pred is None and gold is None:
        return "tn", "tn"
    if pred is not None and gold is None:
        return "fp", "fp"
    if pred is None and gold is not None:
        return "fn", "fn"

    # Normalizacja do porównania
    ps, gs = str(pred).strip(), str(gold).strip()

    if ps == gs:
        return "tp", "tp"

    # Fuzzy
    ratio = fuzz.ratio(ps, gs)
    return "fpfn", ("tp" if ratio >= fuzzy_threshold else "fpfn")


# Zliczanie
exact_total = Counts()
fuzzy_total = Counts()
per_class_exact = {d: Counts() for d in DOC_TYPES}
per_class_fuzzy = {d: Counts() for d in DOC_TYPES}
mismatches = []
files_evaluated = 0
files_missing = 0

set_dirs = sorted(
    [p for p in gold_root.iterdir() if p.is_dir() and p.name.startswith("przyklad_")],
    key=lambda p: int(p.name.split("_")[1]),
)[:n]

for set_dir in set_dirs:
    set_id = set_dir.name
    for doc_type in DOC_TYPES:
        gold_path = gold_root / set_id / f"{doc_type}.json"
        pred_path = pred_root / set_id / f"{doc_type}.json"

        if not gold_path.exists():
            continue

        gold_obj = json.loads(gold_path.read_text())

        if not pred_path.exists():
            files_missing += 1
            # Wszystkie gold pola to FN
            flat_gold = flatten(gold_obj)
            for key, gv in flat_gold.items():
                if gv is not None:
                    exact_total.fn += 1
                    fuzzy_total.fn += 1
                    per_class_exact[doc_type].fn += 1
                    per_class_fuzzy[doc_type].fn += 1
            continue

        files_evaluated += 1
        pred_obj = json.loads(pred_path.read_text())

        flat_gold = flatten(gold_obj)
        flat_pred = flatten(pred_obj)
        all_keys = set(flat_gold.keys()) | set(flat_pred.keys())

        for key in sorted(all_keys):
            gv = flat_gold.get(key)
            pv = flat_pred.get(key)
            ev, fv = compare_values(pv, gv)

            for verdict, counts in [(ev, exact_total), (fv, fuzzy_total)]:
                if verdict == "tp": counts.tp += 1
                elif verdict == "fp": counts.fp += 1
                elif verdict == "fn": counts.fn += 1
                elif verdict == "tn": counts.tn += 1
                elif verdict == "fpfn": counts.fp += 1; counts.fn += 1

            for verdict, counts in [(ev, per_class_exact[doc_type]), (fv, per_class_fuzzy[doc_type])]:
                if verdict == "tp": counts.tp += 1
                elif verdict == "fp": counts.fp += 1
                elif verdict == "fn": counts.fn += 1
                elif verdict == "tn": counts.tn += 1
                elif verdict == "fpfn": counts.fp += 1; counts.fn += 1

            if ev != "tp" and ev != "tn":
                mismatches.append({
                    "set": set_id,
                    "doc": doc_type,
                    "field": key,
                    "gold": gv,
                    "pred": pv,
                    "exact": ev,
                    "fuzzy": fv,
                })

# --- Wypisz raport ---
W = 56

print("=" * W)
print(f"{'WYNIKI EWALUACJI':^{W}}")
print("=" * W)
print(f"  Plików ocenionych:   {files_evaluated}")
print(f"  Plików brakujących:  {files_missing}")
print()

print(f"{'─ OGÓLNE (micro) ─':─^{W}}")
print(f"  {'':20} {'Exact':>12}  {'Fuzzy':>12}")
print(f"  {'Precision':20} {exact_total.precision:12.4f}  {fuzzy_total.precision:12.4f}")
print(f"  {'Recall':20} {exact_total.recall:12.4f}  {fuzzy_total.recall:12.4f}")
print(f"  {'F1':20} {exact_total.f1:12.4f}  {fuzzy_total.f1:12.4f}")
print(f"  {'TP':20} {exact_total.tp:12d}  {fuzzy_total.tp:12d}")
print(f"  {'FP':20} {exact_total.fp:12d}  {fuzzy_total.fp:12d}")
print(f"  {'FN':20} {exact_total.fn:12d}  {fuzzy_total.fn:12d}")
print(f"  {'TN':20} {exact_total.tn:12d}  {fuzzy_total.tn:12d}")
print()

print(f"{'─ PER-CLASS ─':─^{W}}")
print(f"  {'Klasa':20} {'Exact F1':>12}  {'Fuzzy F1':>12}")
for dc in DOC_TYPES:
    print(f"  {dc:20} {per_class_exact[dc].f1:12.4f}  {per_class_fuzzy[dc].f1:12.4f}")
print()

if mismatches:
    print(f"{'─ ROZBIEŻNOŚCI (max 30) ─':─^{W}}")
    for m in mismatches[:30]:
        marker = "≈" if m["fuzzy"] == "tp" else "✗"
        print(f"  {marker} {m['set']}/{m['doc']}")
        print(f"    {m['field']}")
        gold_s = str(m['gold'])[:60]
        pred_s = str(m['pred'])[:60]
        print(f"    gold: {gold_s}")
        print(f"    pred: {pred_s}")
    if len(mismatches) > 30:
        print(f"  ... i {len(mismatches) - 30} więcej")
print()
print("=" * W)
PYEOF
