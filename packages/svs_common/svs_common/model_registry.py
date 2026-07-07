from __future__ import annotations
from functools import lru_cache
import os
from pathlib import Path
from typing import Any
import yaml

CONFIG_DIR = Path(os.getenv("SVS_CONFIG_DIR") or ("configs" if Path("configs").exists() else "/app/configs"))

def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

@lru_cache
def vectorization_modes() -> dict[str, Any]:
    return _load(CONFIG_DIR / "vectorization-modes.yaml").get("modes", {})

@lru_cache
def model_registry() -> dict[str, Any]:
    return _load(CONFIG_DIR / "model-registry.yaml")

@lru_cache
def retrieval_profiles() -> dict[str, Any]:
    return _load(CONFIG_DIR / "retrieval-profiles.yaml").get("profiles", {})

def select_mode(filename: str | None, mime_type: str | None, requested_mode: str | None, metadata: dict | None = None) -> str:
    if requested_mode and requested_mode != "auto_detect_v1":
        return requested_mode
    metadata = metadata or {}
    name, mime = (filename or "").lower(), (mime_type or "").lower()
    if name.endswith(".md") and metadata.get("source_pdf_id"):
        return "pdf_markdown_external_v1"
    if name.endswith(".md") or mime in {"text/markdown", "text/x-markdown"}:
        return "markdown_docs_v1"
    if name.endswith(".pdf") or mime == "application/pdf":
        return "raw_pdf_research_v1"
    if name.endswith((".py", ".ts", ".tsx", ".js", ".java", ".go", ".rs", ".cs", ".php")):
        return "code_repo_v1"
    if name.endswith((".csv", ".json", ".jsonl")):
        return "tables_csv_json_v1"
    return "markdown_docs_v1"

def resolve_vectorization_profile(filename: str | None, mime_type: str | None, requested_mode: str | None, metadata: dict | None = None) -> tuple[str, dict[str, Any]]:
    mode_id = select_mode(filename, mime_type, requested_mode, metadata)
    return mode_id, vectorization_modes().get(mode_id, vectorization_modes().get("markdown_docs_v1", {}))

def resolve_embedding_profile(mode_id: str, security_level: int) -> str:
    modes = vectorization_modes()
    registry = model_registry()
    policies = registry.get("policies", {})
    if security_level >= int(policies.get("require_private_provider_above_security_level", 4)):
        return policies.get("fallback_private_embedding_profile", "bge_m3_local")
    return modes.get(mode_id, {}).get("embedding_profile") or policies.get("default_embedding_profile", "openai_text_embedding_3_small_1536")
