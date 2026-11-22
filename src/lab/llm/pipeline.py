"""End-to-end OCR-text -> LLM -> validated JSON pipeline for a whole run.

Predictions are written as `<run_dir>/<set_id>/<gold_stem>.json`, so an
existing `lab eval --run <run_dir>` reads them without copying anything.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from o2jcore.spec.jsonschema_build import build_json_schema
from o2jcore.spec.models import DocClassSpec
from o2jcore.spec.pydantic_build import build_model
from o2jcore.text.pdf_text import extract_pages

from lab.cache import pdf_content_hash, read_cached, write_cache
from lab.llm.classify import classify_document
from lab.llm.client import LLMClient, LLMResponse, unwrap_json
from lab.llm.config import ExperimentConfig, ModelConfig
from lab.llm.grounding import enforce_derived, ground_object
from lab.llm.prompts import PromptSet, schema_key_paths
from lab.llm.text_prep import candidate_hints, prepare_ocr_text
from lab.manifest import run_dir_name

_TITLE_RE = re.compile(
    r"^(?:(?:r\.\s*pr\.|radca\s+prawny|adw\.|mec\.|mgr|dr)\.?\s*)+",
    re.IGNORECASE,
)
_DOTS_RE = re.compile(r"^\.{8,}$")
_SIGN_ROLES = (
    "Wiceprezes",
    "Członek Zarządu",
    "Główny Księgowy",
    "Osoba upoważniona",
    "Radca prawny",
    "Prokurent",
    "Dyrektor",
    "Prezes",
    "Kierownik",
    "Adwokat",
    "Pełnomocnik",
)


def _parse_sign_roles(line: str) -> list[str]:
    rest = line.strip()
    roles: list[str] = []
    while rest:
        matched = False
        for role in _SIGN_ROLES:
            if rest.lower().startswith(role.lower()):
                roles.append(role)
                rest = rest[len(role) :].strip(" ,;")
                matched = True
                break
        if not matched:
            return []
    return roles


def _signature_names(text: str) -> list[str]:
    lines = [line.strip() for line in text.splitlines()]
    names: list[str] = []
    for index in range(len(lines) - 2):
        if not _DOTS_RE.match(lines[index]):
            continue
        roles = _parse_sign_roles(lines[index + 2])
        if not roles:
            continue
        tokens = lines[index + 1].split()
        if len(tokens) == 2 * len(roles):
            names.extend(
                " ".join(tokens[offset : offset + 2])
                for offset in range(0, len(tokens), 2)
            )
        elif len(roles) == 1 and len(tokens) == 2:
            names.append(lines[index + 1].strip())
    return names


def repair_signature_names(obj: dict[str, Any], text: str) -> dict[str, Any]:
    """Fill signatory names from the signature block when the layout is clear."""
    mocodawcy = obj.get("mocodawca")
    if not isinstance(mocodawcy, list) or len(mocodawcy) != 1:
        return obj
    names = _signature_names(text)
    if not names:
        return obj
    mocodawcy[0]["podpisujacy"] = [{"imie_nazwisko": name} for name in names]
    return obj


def _person_names(value: Any) -> list[str] | None:
    if not isinstance(value, str) or "," not in value:
        return None
    parts = [part.strip() for part in value.split(",") if part.strip()]
    if len(parts) < 2:
        return None
    cleaned = [_TITLE_RE.sub("", part).strip() for part in parts]
    if any(not name or any(ch.isdigit() for ch in name) for name in cleaned):
        return None
    if any(len(name.split()) < 2 for name in cleaned):
        return None
    return cleaned


def split_combined_names(obj: dict[str, Any]) -> dict[str, Any]:
    """Split comma-joined person names into separate list objects where possible."""
    names = _person_names(obj.get("imie_nazwisko"))
    if names:
        obj["imie_nazwisko"] = names[0]
    for value in obj.values():
        if isinstance(value, dict):
            split_combined_names(value)
        elif isinstance(value, list):
            new_items: list[Any] = []
            for item in value:
                if not isinstance(item, dict):
                    new_items.append(item)
                    continue
                extra_names = _person_names(item.get("imie_nazwisko"))
                if extra_names:
                    for name in extra_names:
                        new_items.append(
                            {**item, "imie_nazwisko": name}
                        )
                else:
                    split_combined_names(item)
                    new_items.append(item)
            value[:] = new_items
    return obj


@dataclass
class Extraction:
    obj: dict[str, Any] | None
    raw: list[str] = field(default_factory=list)
    responses: list[LLMResponse] = field(default_factory=list)
    retries: int = 0
    error: str | None = None
    grounded: int = 0
    derived: int = 0


@dataclass
class DocumentOutcome:
    set_id: str
    class_id: str
    pdf_path: Path
    text: str
    classification: str | None
    extraction: Extraction
    classification_response: LLMResponse | None = None

    @property
    def ok(self) -> bool:
        return self.extraction.obj is not None

    @property
    def all_responses(self) -> list[LLMResponse]:
        """Classification and extraction calls, for honest usage accounting."""
        cls = [self.classification_response] if self.classification_response is not None else []
        return cls + self.extraction.responses


@dataclass
class PipelineResult:
    run_dir: Path
    outcomes: list[DocumentOutcome] = field(default_factory=list)

    @property
    def prompt_tokens(self) -> int:
        return sum(r.prompt_tokens for o in self.outcomes for r in o.all_responses)

    @property
    def completion_tokens(self) -> int:
        return sum(r.completion_tokens for o in self.outcomes for r in o.all_responses)

    @property
    def seconds(self) -> float:
        return sum(r.seconds for o in self.outcomes for r in o.all_responses)

    @property
    def retries(self) -> int:
        return sum(o.extraction.retries for o in self.outcomes)

    @property
    def invalid_json(self) -> int:
        return sum(1 for o in self.outcomes if not o.ok)

    @property
    def structured_calls(self) -> int:
        return sum(1 for o in self.outcomes for r in o.all_responses if r.structured)

    @property
    def llm_calls(self) -> int:
        return sum(len(o.all_responses) for o in self.outcomes)


def _load_pages(pdf_path: Path, cache_root: Path, extractor: str) -> list[Any]:
    digest = pdf_content_hash(pdf_path)
    cached = read_cached(cache_root, pdf_path, extractor, content_hash=digest)
    if cached is not None:
        return cached["pages"]
    pages = extract_pages(pdf_path, extractor)
    write_cache(cache_root, pdf_path, extractor, pages, content_hash=digest)
    return [
        {"n": page.n, "text": page.text, "width": page.width, "height": page.height}
        for page in pages
    ]


_LABEL_ALIASES = {
    "kwota operacji": "kwota",
    "kwota przelewu": "kwota",
    "data transakcji": "data_operacji",
    "data operacji": "data_operacji",
    "data wykonania operacji": "data_operacji",
    "tytuł przelewu": "tytul",
    "tytuł operacji": "tytul",
    "nr ref": "numer_transakcji",
    "numer referencyjny": "numer_transakcji",
    "numer transakcji": "numer_transakcji",
    "numer operacji": "numer_transakcji",
}
_CONTAINER_ACCOUNT_FIELDS = {
    "płatnik": "z_rachunku",
    "nadawca": "z_rachunku",
    "adresat przelewu": "na_rachunek",
    "adresat": "na_rachunek",
    "odbiorca": "na_rachunek",
}


def _normalize_label(label: str) -> str:
    return re.sub(r"\s+", " ", str(label).strip().lower()).rstrip(".: ")


def _filter_to_schema(payload: dict[str, Any], node: dict[str, Any]) -> dict[str, Any]:
    properties = node.get("properties", {})
    filtered: dict[str, Any] = {}
    for key, value in payload.items():
        if key not in properties:
            continue
        child = properties[key]
        if isinstance(value, dict) and "properties" in child:
            filtered[key] = _filter_to_schema(value, child)
        elif isinstance(value, list) and "items" in child and "properties" in child["items"]:
            filtered[key] = [
                _filter_to_schema(item, child["items"]) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            filtered[key] = value
    return filtered


def map_polish_labels(payload: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    properties = schema.get("properties", {})
    root_keys = list(properties)
    mapped: dict[str, Any] = {
        key: dict(value) if isinstance(value, dict) else list(value)
        for key, value in payload.items()
        if key in root_keys and isinstance(value, (dict, list))
    }
    for root_key in root_keys:
        mapped.setdefault(root_key, {})
    top = mapped.get(root_keys[0]) if root_keys else None
    if not isinstance(top, dict):
        return mapped

    for label, value in payload.items():
        if label in root_keys:
            continue
        if "." in label:
            parts = label.split(".")
            if parts[0] in root_keys:
                target = mapped[parts[0]]
                for part in parts[1:-1]:
                    if not isinstance(target, dict):
                        break
                    target = target.setdefault(part, {})
                if isinstance(target, dict):
                    target[parts[-1]] = value
                continue
        normalized = _normalize_label(label)
        if normalized in _CONTAINER_ACCOUNT_FIELDS and isinstance(value, dict):
            account_field = _CONTAINER_ACCOUNT_FIELDS[normalized]
            for child_label, child_value in value.items():
                if _normalize_label(child_label) == "rachunek":
                    top[account_field] = child_value
                    break
            continue
        field = _LABEL_ALIASES.get(normalized)
        if field:
            top[field] = value

    for root_key in root_keys:
        if isinstance(mapped.get(root_key), dict):
            mapped[root_key] = _filter_to_schema(mapped[root_key], properties[root_key])
    return mapped


def coerce_list_fields(payload: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    """Doprowadź pola-listy do postaci oczekiwanej przez model Pydantic.

    Wymuszany dekoder llama.cpp potrafi zwrócić ``{}`` zamiast ``[]`` dla pustej
    tablicy obiektów (np. ``Odwolujacy``/``Zamawiajacy``). Bez tej korekty cały
    wynik LLM jest odrzucany przez walidację i ląduje jako ``raw_text``.
    Pojedynczy obiekt zostaje owinięty w listę, ``null`` staje się pustą listą.
    """
    properties = schema.get("properties", {})
    out: dict[str, Any] = {}
    for key, value in payload.items():
        child = properties.get(key)
        if child is None:
            out[key] = value
            continue
        types = child.get("type")
        if isinstance(types, str):
            types = [types]
        if "array" in (types or []):
            if isinstance(value, dict):
                value = [value] if value else []
            elif value is None:
                value = []
            items = child.get("items", {})
            if isinstance(value, list) and isinstance(items, dict) and "properties" in items:
                value = [
                    coerce_list_fields(item, items) if isinstance(item, dict) else item
                    for item in value
                ]
        elif isinstance(value, dict) and isinstance(child, dict) and "properties" in child:
            value = coerce_list_fields(value, child)
        out[key] = value
    return out


def resolve_set_ids(
    experiment: ExperimentConfig,
    data_root: Path,
    work_root: Path,
    set_ids: list[str] | None = None,
) -> list[str]:
    if set_ids is None:
        if experiment.split in ("dev", "holdout"):
            splits_path = work_root / "splits.json"
            if not splits_path.exists():
                raise FileNotFoundError(f"no split found at {splits_path}; run `lab split` first")
            with splits_path.open("r", encoding="utf-8") as f:
                set_ids = list(json.load(f)[experiment.split])
        else:
            data_dir = Path(data_root) / "dane"
            set_ids = [
                p.name
                for p in sorted(data_dir.glob("przyklad_*"))
                if p.is_dir()
            ]
    if experiment.limit is not None:
        set_ids = set_ids[: experiment.limit]
    return list(set_ids)


def extract_document(
    client: LLMClient,
    prompts: PromptSet,
    spec: DocClassSpec,
    text: str,
    *,
    schema: dict[str, Any] | None = None,
    candidates: str | None = None,
    retries: int = 1,
    ground_null: bool = False,
) -> Extraction:
    model = build_model(spec)
    active_schema = schema if schema is not None else build_json_schema(spec)
    system = prompts.render("rules.j2")
    key_paths = [] if client.model.structured_output else schema_key_paths(active_schema)
    user = prompts.extract(spec.id, text, candidates=candidates, keys=key_paths)
    result = Extraction(obj=None)

    for attempt in range(retries + 1):
        try:
            response = client.call_json(system, user, active_schema)
        except Exception as exc:
            result.error = f"LLMError: {exc}"[:1500]
            if attempt < retries:
                result.retries += 1
                continue
            return result
        result.responses.append(response)
        result.raw.append(response.text)
        try:
            parsed = json.loads(unwrap_json(response.text))
            if not isinstance(parsed, dict):
                raise ValueError("model response is not a JSON object")
            mapped = map_polish_labels(parsed, active_schema)
            obj = model.model_validate(coerce_list_fields(mapped, active_schema)).model_dump()
            obj = split_combined_names(obj)
            obj = repair_signature_names(obj, text)
        except Exception as exc:
            result.error = f"{type(exc).__name__}: {exc}"[:1500]
            if attempt < retries:
                result.retries += 1
                user = prompts.repair(result.raw[-1], result.error)
                continue
            return result

        if ground_null:
            result.grounded = ground_object(obj, spec, text)
        result.derived = enforce_derived(obj, spec)
        obj = model.model_validate(obj).model_dump()
        result.obj = obj
        result.error = None
        return result

    return result


def _usage_fields(responses: list[LLMResponse]) -> dict[str, Any]:
    return {
        "prompt_tokens": sum(r.prompt_tokens for r in responses),
        "completion_tokens": sum(r.completion_tokens for r in responses),
        "seconds": round(sum(r.seconds for r in responses), 4),
        "calls": len(responses),
        "structured_calls": sum(1 for r in responses if r.structured),
    }


def _write_raw(run_dir: Path, set_id: str, stem: str, extraction: Extraction) -> None:
    raw_dir = run_dir / "raw" / set_id
    raw_dir.mkdir(parents=True, exist_ok=True)
    for index, raw in enumerate(extraction.raw):
        (raw_dir / f"{stem}_{index}.txt").write_text(raw, encoding="utf-8")


def run_pipeline(
    *,
    experiment: ExperimentConfig,
    model: ModelConfig,
    specs: dict[str, DocClassSpec],
    data_root: Path,
    work_root: Path,
    run_dir: Path | None = None,
    set_ids: list[str] | None = None,
    client: LLMClient | None = None,
    prompts: PromptSet | None = None,
    class_ids: list[str] | None = None,
) -> PipelineResult:
    resolved_run_dir = (
        Path(run_dir)
        if run_dir is not None
        else Path(work_root) / "runs" / run_dir_name(experiment.name, model.id)
    )
    resolved_run_dir.mkdir(parents=True, exist_ok=True)
    resolved_prompts = prompts if prompts is not None else PromptSet()
    active_client = client if client is not None else LLMClient(model)
    ids = resolve_set_ids(experiment, data_root, work_root, set_ids)

    data_dir = Path(data_root) / "dane"
    cache_root = Path(work_root) / "cache"
    schemas = {cid: build_json_schema(spec) for cid, spec in specs.items()}
    classifications: dict[str, str | None] = {}
    usages: list[dict[str, Any]] = []
    result = PipelineResult(run_dir=resolved_run_dir)
    wanted_stems = {
        stem
        for cid in (class_ids or [])
        for spec in [specs.get(cid)]
        if spec is not None
        for stem in (spec.pdf_stem, spec.gold_stem)
    }

    for set_id in ids:
        for pdf_path in sorted((data_dir / set_id).glob("*.pdf")):
            if wanted_stems and pdf_path.stem not in wanted_stems:
                continue
            pages = _load_pages(pdf_path, cache_root, experiment.extractor)
            text = prepare_ocr_text(
                pages,
                trim=experiment.trim,
                head_chars=experiment.head_chars,
                tail_chars=experiment.tail_chars,
            )
            classification: str | None = None
            cls_response: LLMResponse | None = None
            try:
                classification, cls_response = classify_document(
                    active_client, resolved_prompts, text, experiment.classify_method
                )
            except Exception:
                pass

            if classification not in specs or (
                class_ids is not None and classification not in class_ids
            ):
                # A rejected document still belongs to its resolved class's
                # gold stem (e.g. przelew.json for a transfer), not to the
                # PDF's on-disk name. Unknown classes keep the PDF stem.
                stem = specs[classification].gold_stem if classification in specs else pdf_path.stem
                rel_path = f"{set_id}/{stem}.json"
                classifications[rel_path] = classification
                pred_path = resolved_run_dir / rel_path
                pred_path.parent.mkdir(parents=True, exist_ok=True)
                pred_path.write_bytes(b"")
                cls_usage = _usage_fields([cls_response] if cls_response is not None else [])
                usages.append(
                    {
                        "file": rel_path,
                        "class": classification,
                        "classification": classification,
                        **cls_usage,
                        "retries": 0,
                        "grounded": 0,
                        "derived": 0,
                        "error": "rejected: class not recognized",
                    }
                )
                result.outcomes.append(
                    DocumentOutcome(
                        set_id,
                        classification or "",
                        pdf_path,
                        text,
                        classification,
                        Extraction(obj=None, error="rejected: class not recognized"),
                        classification_response=cls_response,
                    )
                )
                continue

            spec = specs[classification]
            hints = candidate_hints(text) if experiment.candidates else None
            extraction = extract_document(
                active_client,
                resolved_prompts,
                spec,
                text,
                schema=schemas[classification],
                candidates=hints,
                retries=experiment.retry_on_invalid,
                ground_null=experiment.ground_null,
            )
            _write_raw(resolved_run_dir, set_id, pdf_path.stem, extraction)

            rel_path = f"{set_id}/{spec.gold_stem}.json"
            classifications[rel_path] = classification
            if extraction.obj is not None:
                pred_path = resolved_run_dir / rel_path
                pred_path.parent.mkdir(parents=True, exist_ok=True)
                with pred_path.open("w", encoding="utf-8") as f:
                    json.dump(extraction.obj, f, indent=2, ensure_ascii=False)
                    f.write("\n")

            all_responses = (
                ([cls_response] if cls_response is not None else []) + extraction.responses
            )
            usages.append(
                {
                    "file": rel_path,
                    "class": classification,
                    "classification": classification,
                    **_usage_fields(all_responses),
                    "retries": extraction.retries,
                    "grounded": extraction.grounded,
                    "derived": extraction.derived,
                    "error": extraction.error,
                }
            )
            result.outcomes.append(
                DocumentOutcome(
                    set_id,
                    classification,
                    pdf_path,
                    text,
                    classification,
                    extraction,
                    classification_response=cls_response,
                )
            )

    with (resolved_run_dir / "classification.json").open("w", encoding="utf-8") as f:
        json.dump(classifications, f, indent=2, ensure_ascii=False)
        f.write("\n")
    with (resolved_run_dir / "usage.json").open("w", encoding="utf-8") as f:
        json.dump(usages, f, indent=2, ensure_ascii=False)
        f.write("\n")

    return result
