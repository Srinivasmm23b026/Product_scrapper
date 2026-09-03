from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol
from urllib.parse import quote

import requests

from procurement_assistant.providers.auth.supabase import validate_supabase_url
from procurement_assistant.settings import Settings


class ObjectStorage(Protocol):
    def put_json(self, key: str, value: object) -> str: ...


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, default=str, ensure_ascii=False).encode("utf-8")


class LocalObjectStorage:
    def __init__(self, root: Path):
        self.root = root.resolve()

    def put_json(self, key: str, value: object) -> str:
        target = (self.root / key).resolve()
        if self.root not in target.parents:
            raise ValueError("storage key escapes configured root")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(_json_bytes(value))
        return str(target)


class SupabaseObjectStorage:
    def __init__(
        self,
        *,
        url: str,
        service_role_key: str,
        bucket: str,
        timeout_seconds: int = 15,
        session: requests.Session | None = None,
    ):
        self.url = validate_supabase_url(url)
        self.service_role_key = service_role_key
        self.bucket = bucket
        self.timeout_seconds = timeout_seconds
        self.session = session or requests.Session()

    def put_json(self, key: str, value: object) -> str:
        encoded_key = "/".join(quote(part, safe="") for part in key.split("/"))
        headers = {
            "apikey": self.service_role_key,
            "Content-Type": "application/json",
            "x-upsert": "false",
        }
        # Legacy service_role keys are JWTs and require the bearer header. Current sb_secret
        # keys authenticate through apikey only and must not be presented as bearer JWTs.
        if not self.service_role_key.startswith("sb_"):
            headers["Authorization"] = f"Bearer {self.service_role_key}"
        response = self.session.post(
            f"{self.url}/storage/v1/object/{quote(self.bucket, safe='')}/{encoded_key}",
            headers=headers,
            data=_json_bytes(value),
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        return f"supabase://{self.bucket}/{key}"


class S3ObjectStorage:
    def __init__(self, *, bucket: str, region: str):
        import boto3

        self.bucket = bucket
        self.client = boto3.client("s3", region_name=region)

    def put_json(self, key: str, value: object) -> str:
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=_json_bytes(value),
            ContentType="application/json",
            ServerSideEncryption="AES256",
        )
        return f"s3://{self.bucket}/{key}"


def configure_storage(settings: Settings) -> ObjectStorage:
    if settings.object_storage_provider == "supabase":
        if not settings.supabase_url or not settings.supabase_service_role_key:
            raise ValueError("Supabase storage requires SUPABASE_URL and a server secret key")
        return SupabaseObjectStorage(
            url=settings.supabase_url,
            service_role_key=settings.supabase_service_role_key,
            bucket=settings.object_storage_bucket,
            timeout_seconds=settings.provider_timeout_seconds,
        )
    if settings.object_storage_provider == "s3":
        if not settings.raw_snapshot_bucket:
            raise ValueError("S3 storage requires RAW_SNAPSHOT_BUCKET")
        return S3ObjectStorage(bucket=settings.raw_snapshot_bucket, region=settings.aws_region)
    return LocalObjectStorage(settings.local_storage_path)
