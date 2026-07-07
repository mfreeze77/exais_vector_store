from __future__ import annotations
from pathlib import Path
import yaml
from .schemas import InstanceManifest

def load_instance_manifest(path: str | Path) -> InstanceManifest:
    return InstanceManifest.model_validate(yaml.safe_load(Path(path).read_text()))

def render_compose_project_name(manifest: InstanceManifest) -> str:
    return manifest.runtime.get("composeProjectName") or f"svs_{manifest.metadata.get('slug', manifest.metadata.get('instanceId', 'instance'))}".replace("-", "_")
