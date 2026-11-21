"""Jinja2 prompt templates and their content hashes for run manifests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from lab.paths import REPO_ROOT

DEFAULT_PROMPTS_DIR = REPO_ROOT / "configs" / "prompts"


def schema_key_paths(schema: dict[str, Any]) -> list[str]:
    paths: list[str] = []

    def walk(node: dict[str, Any], prefix: str) -> None:
        for key, child in node.get("properties", {}).items():
            path = f"{prefix}.{key}" if prefix else key
            paths.append(path)
            if "properties" in child:
                walk(child, path)
            elif "items" in child and "properties" in child["items"]:
                walk(child["items"], f"{path}[]")

    walk(schema, "")
    return paths


class PromptSet:
    def __init__(self, dir_path: Path | None = None) -> None:
        self.dir = Path(dir_path) if dir_path is not None else DEFAULT_PROMPTS_DIR
        if not self.dir.is_dir():
            raise FileNotFoundError(f"prompts directory not found: {self.dir}")
        self.env = Environment(
            loader=FileSystemLoader(self.dir),
            undefined=StrictUndefined,
            keep_trailing_newline=True,
            autoescape=False,
        )

    def render(self, template_name: str, **context: Any) -> str:
        return self.env.get_template(template_name).render(**context)

    def extract(
        self,
        class_id: str,
        text: str,
        *,
        candidates: str | None = None,
        examples: list[dict[str, Any]] | None = None,
        keys: list[str] | None = None,
    ) -> str:
        user = self.render(
            f"extract_{class_id}.j2",
            text=text,
            candidates=candidates,
            keys=keys or [],
        )
        if examples:
            block = "\n".join(
                f"<przyklad>\n{json.dumps(ex, ensure_ascii=False)}\n</przyklad>" for ex in examples
            )
            user = f"<przyklady>\n{block}\n</przyklady>\n\n{user}"
        return user

    def classify(self, text: str) -> str:
        return self.render("classify.j2", text=text[:1500])

    def repair(self, raw: str, error: str) -> str:
        return self.render("repair.j2", raw=raw, error=error)

    def sha256(self) -> dict[str, str]:
        hashes = {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(self.dir.glob("*.j2"))
        }
        combined = "".join(f"{name}:{digest}\n" for name, digest in sorted(hashes.items()))
        hashes["all"] = hashlib.sha256(combined.encode("utf-8")).hexdigest()
        return hashes
