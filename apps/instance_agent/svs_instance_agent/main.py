from __future__ import annotations
import os
import subprocess
from pathlib import Path
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from svs_common.config import get_settings
from svs_common.instance_manifest import load_instance_manifest, render_compose_project_name

settings = get_settings()
settings.validate_runtime_guards()
WORKDIR = Path(os.getenv('SVS_AGENT_WORKDIR', '/workspace'))
if not WORKDIR.exists():
    WORKDIR = Path.cwd()
app = FastAPI(title='exai_vector_store Instance Agent', version=settings.svs_product_version)

class DeployRequest(BaseModel):
    manifest_path: str
    version: str | None = None
    dry_run: bool = False

class BackupRequest(BaseModel):
    manifest_path: str
    dest_root: str = 'backups'

class RollbackRequest(BaseModel):
    manifest_path: str
    version: str
    dry_run: bool = False


def run(cmd: list[str], cwd: str | None = None) -> dict:
    proc = subprocess.run(cmd, cwd=cwd or str(WORKDIR), capture_output=True, text=True)
    return {'command': cmd, 'returncode': proc.returncode, 'stdout': proc.stdout, 'stderr': proc.stderr}


def require_success(result: dict) -> dict:
    if result['returncode'] != 0:
        raise HTTPException(status_code=500, detail=result)
    return result


@app.get('/healthz')
def healthz():
    return {'ok': True, 'service': 'svs-instance-agent', 'version': settings.svs_product_version}


@app.post('/agent/v1/instances/deploy')
def deploy(req: DeployRequest):
    path = Path(req.manifest_path)
    if not path.is_absolute():
        path = WORKDIR / path
    if not path.exists():
        raise HTTPException(status_code=404, detail='Manifest not found')
    manifest = load_instance_manifest(path)
    project = render_compose_project_name(manifest)
    env = os.environ.copy()
    if req.version:
        env['SVS_PRODUCT_VERSION'] = req.version
    if req.dry_run:
        return {'dry_run': True, 'compose_project_name': project, 'manifest': manifest.model_dump(), 'version': req.version}
    pull = run(['docker', 'compose', '-p', project, 'pull'])
    if pull['returncode'] != 0:
        raise HTTPException(status_code=500, detail={'step': 'pull', **pull})
    up = run(['docker', 'compose', '-p', project, 'up', '-d'])
    if up['returncode'] != 0:
        raise HTTPException(status_code=500, detail={'step': 'up', **up})
    ps = run(['docker', 'compose', '-p', project, 'ps'])
    return {'project': project, 'version': req.version, 'pull': pull, 'up': up, 'ps': ps}


@app.post('/agent/v1/instances/backup')
def backup(req: BackupRequest):
    path = Path(req.manifest_path)
    if not path.is_absolute():
        path = WORKDIR / path
    if not path.exists():
        raise HTTPException(status_code=404, detail='Manifest not found')
    result = require_success(run(['bash', 'scripts/backup-instance.sh', str(path), req.dest_root]))
    return {'status': 'completed', 'bundle': result['stdout'].strip().splitlines()[-1] if result['stdout'].strip() else None, 'result': result}


@app.post('/agent/v1/instances/rollback')
def rollback(req: RollbackRequest):
    path = Path(req.manifest_path)
    if not path.is_absolute():
        path = WORKDIR / path
    if not path.exists():
        raise HTTPException(status_code=404, detail='Manifest not found')
    # Rollback is a deployment of a previously pinned version. Data rollback is handled by restore.
    dep = DeployRequest(manifest_path=req.manifest_path, version=req.version, dry_run=req.dry_run)
    return {'status': 'rolled_back' if not req.dry_run else 'planned', 'deployment': deploy(dep)}
