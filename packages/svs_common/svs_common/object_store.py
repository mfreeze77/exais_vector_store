from __future__ import annotations
from pathlib import Path
from .config import get_settings

class ObjectStoreError(RuntimeError):
    pass

class ObjectStore:
    def __init__(self):
        self.settings = get_settings()
        self.client = None
        self.init_error: str | None = None
        if self.settings.s3_endpoint_url:
            try:
                import boto3
                self.client = boto3.client(
                    's3',
                    endpoint_url=self.settings.s3_endpoint_url,
                    aws_access_key_id=self.settings.s3_access_key_id,
                    aws_secret_access_key=self.settings.s3_secret_access_key,
                    region_name=self.settings.s3_region,
                )
            except Exception as exc:
                self.init_error = str(exc)
                self.client = None

    def _local_path(self, key: str) -> Path:
        safe = key.strip('/').replace('..', '_')
        return self.settings.local_object_store_root / safe

    def put_text(self, key: str, text: str, content_type: str = 'text/plain') -> str:
        body = text.encode('utf-8')
        if self.client:
            try:
                self.client.put_object(Bucket=self.settings.s3_bucket, Key=key, Body=body, ContentType=content_type)
                return key
            except Exception as exc:
                if self.settings.svs_object_store_strict:
                    raise ObjectStoreError(f'object-store put failed for {key}: {exc}') from exc
        elif self.settings.svs_object_store_strict:
            raise ObjectStoreError(f'object-store client unavailable: {self.init_error or "not configured"}')
        # Local fallback makes single-VPS micro cells self-contained and testable.
        path = self._local_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        return key

    def get_text(self, key: str) -> str:
        if self.client:
            try:
                obj = self.client.get_object(Bucket=self.settings.s3_bucket, Key=key)
                return obj['Body'].read().decode('utf-8')
            except Exception as exc:
                if self.settings.svs_object_store_strict:
                    raise ObjectStoreError(f'object-store get failed for {key}: {exc}') from exc
        path = self._local_path(key)
        return path.read_text(encoding='utf-8') if path.exists() else ''

    def exists(self, key: str) -> bool:
        if self.client:
            try:
                self.client.head_object(Bucket=self.settings.s3_bucket, Key=key)
                return True
            except Exception:
                pass
        return self._local_path(key).exists()
