from __future__ import annotations
import uuid

SVS_POINT_NAMESPACE = uuid.UUID("9e2841fb-5d1d-4e43-8d7f-4d9b65a512a8")

def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:24]}"

def point_uuid(stable_id: str) -> str:
    """Return a deterministic UUID string suitable for Qdrant point IDs."""
    return str(uuid.uuid5(SVS_POINT_NAMESPACE, stable_id))
