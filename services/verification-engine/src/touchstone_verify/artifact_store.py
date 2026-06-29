"""Artifact store — resolves an ``artifact_ref`` to the object under test.

The control-plane stores only a reference (an S3 key or a file path); the raw
artifact (model output, trajectory) lives in object storage. The engine loads it
at execution time. Two backends implement one interface, selected by the scheme
of the configured base URI, so the worker is unaware of which is in use:

  * ``file://`` — local dev/CI.
  * ``s3://``   — production object storage (AWS S3 / S3-compatible).

``boto3`` is an optional dependency (install the ``s3`` extra); it is imported
lazily so a ``file://`` deployment never needs it.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse


class _Backend(Protocol):
    async def load(self, artifact_ref: str) -> object: ...
    async def save(self, artifact_ref: str, content: object) -> None: ...


def _decode(raw: str) -> object:
    """JSON is decoded; anything else is returned as text."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


class ArtifactStore:
    """Backend-agnostic facade. Dispatches to the backend for the base scheme."""

    def __init__(self, base_uri: str, *, s3_client: Any | None = None) -> None:
        self._base_uri = base_uri.rstrip("/")
        scheme = urlparse(base_uri).scheme or "file"
        self._scheme = scheme
        if scheme == "file":
            self._backend: _Backend = _FileBackend(base_uri)
        elif scheme == "s3":
            self._backend = _S3Backend(base_uri, client=s3_client)
        else:
            raise ValueError(f"unsupported artifact store scheme: {scheme}")

    @property
    def scheme(self) -> str:
        return self._scheme

    async def load(self, artifact_ref: str) -> object:
        """Return the artifact. JSON is decoded; anything else returned as text."""
        return await self._backend.load(artifact_ref)

    async def save(self, artifact_ref: str, content: object) -> None:
        """Seed an artifact (used by tests/fixtures and producers)."""
        await self._backend.save(artifact_ref, content)


class _FileBackend:
    """Local filesystem backend (dev/CI)."""

    def __init__(self, base_uri: str) -> None:
        parsed = urlparse(base_uri)
        self._root = Path(parsed.path or "/tmp/touchstone-artifacts")

    def _resolve(self, artifact_ref: str) -> Path:
        # Accept either a bare key or a full file:// URI.
        if artifact_ref.startswith("file://"):
            return Path(urlparse(artifact_ref).path)
        # Prevent path traversal outside the configured root.
        candidate = (self._root / artifact_ref.lstrip("/")).resolve()
        if not str(candidate).startswith(str(self._root.resolve())):
            raise ValueError("artifact_ref escapes the artifact root")
        return candidate

    async def load(self, artifact_ref: str) -> object:
        path = self._resolve(artifact_ref)
        raw = await asyncio.to_thread(path.read_text, "utf-8")
        return _decode(raw)

    async def save(self, artifact_ref: str, content: object) -> None:
        path = self._resolve(artifact_ref)
        text = content if isinstance(content, str) else json.dumps(content)

        def _write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")

        await asyncio.to_thread(_write)


class _S3Backend:
    """AWS S3 (or S3-compatible) backend.

    Built from an ``s3://bucket[/prefix]`` base URI. An ``artifact_ref`` is either
    a bare key (resolved under the configured prefix) or a full ``s3://`` URI
    (used verbatim). The blocking boto3 calls run in a worker thread so the async
    worker loop is never blocked.
    """

    def __init__(self, base_uri: str, *, client: Any | None = None) -> None:
        parsed = urlparse(base_uri)
        if not parsed.netloc:
            raise ValueError("s3 base URI must include a bucket, e.g. s3://my-bucket/prefix")
        self._bucket = parsed.netloc
        self._prefix = parsed.path.strip("/")
        self._client = client

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                import boto3  # lazy: only required for the s3 backend
            except ImportError as exc:  # pragma: no cover - import-guard
                raise RuntimeError(
                    "the s3 artifact backend requires boto3; install the 's3' extra "
                    "(pip install 'touchstone-verification-engine[s3]')"
                ) from exc
            self._client = boto3.client("s3")
        return self._client

    def _resolve(self, artifact_ref: str) -> tuple[str, str]:
        if artifact_ref.startswith("s3://"):
            parsed = urlparse(artifact_ref)
            return parsed.netloc, parsed.path.lstrip("/")
        key = artifact_ref.lstrip("/")
        if ".." in key.split("/"):
            raise ValueError("artifact_ref must not contain '..' segments")
        full_key = f"{self._prefix}/{key}" if self._prefix else key
        return self._bucket, full_key

    async def load(self, artifact_ref: str) -> object:
        bucket, key = self._resolve(artifact_ref)
        client = self._get_client()

        def _get() -> bytes:
            resp = client.get_object(Bucket=bucket, Key=key)
            return resp["Body"].read()

        raw = await asyncio.to_thread(_get)
        return _decode(raw.decode("utf-8"))

    async def save(self, artifact_ref: str, content: object) -> None:
        bucket, key = self._resolve(artifact_ref)
        client = self._get_client()
        text = content if isinstance(content, str) else json.dumps(content)

        def _put() -> None:
            client.put_object(Bucket=bucket, Key=key, Body=text.encode("utf-8"))

        await asyncio.to_thread(_put)
