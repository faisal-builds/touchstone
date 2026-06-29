"""Artifact store tests — the file backend and the S3 backend (via moto).

The S3 backend is exercised against an in-process mock of AWS S3 (moto), so the
get/put paths, prefix resolution, and JSON/text decoding are covered for real
without touching AWS.
"""

from __future__ import annotations

import boto3
import pytest
from moto import mock_aws

from touchstone_verify.artifact_store import ArtifactStore

REGION = "us-east-1"


@pytest.fixture
def aws_credentials(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", REGION)


# --- file backend (parity / regression) -------------------------------------

async def test_file_backend_roundtrip_json(tmp_path):
    store = ArtifactStore(f"file://{tmp_path}")
    await store.save("run/out.json", {"answer": 42})
    loaded = await store.load("run/out.json")
    assert loaded == {"answer": 42}
    assert store.scheme == "file"


async def test_file_backend_returns_text_for_non_json(tmp_path):
    store = ArtifactStore(f"file://{tmp_path}")
    await store.save("notes.txt", "just text")
    assert await store.load("notes.txt") == "just text"


def test_unsupported_scheme_rejected():
    with pytest.raises(ValueError, match="unsupported artifact store scheme"):
        ArtifactStore("gs://bucket/prefix")


# --- s3 backend (moto) ------------------------------------------------------
# NOTE: moto's mock_aws is used as a context manager (not a decorator) so it
# composes correctly with async test functions under pytest-asyncio auto mode.

async def test_s3_backend_roundtrip_json(aws_credentials):
    with mock_aws():
        client = boto3.client("s3", region_name=REGION)
        client.create_bucket(Bucket="artifacts")

        store = ArtifactStore("s3://artifacts/prod")
        await store.save("run/out.json", {"score": 1.0})

        # The object lands under the configured prefix.
        body = client.get_object(Bucket="artifacts", Key="prod/run/out.json")["Body"].read()
        assert body == b'{"score": 1.0}'

        # And round-trips back through the store as decoded JSON.
        assert await store.load("run/out.json") == {"score": 1.0}
        assert store.scheme == "s3"


async def test_s3_backend_decodes_text(aws_credentials):
    with mock_aws():
        boto3.client("s3", region_name=REGION).create_bucket(Bucket="artifacts")
        store = ArtifactStore("s3://artifacts")
        await store.save("plain", "hello world")
        assert await store.load("plain") == "hello world"


async def test_s3_backend_accepts_full_uri_ref(aws_credentials):
    with mock_aws():
        client = boto3.client("s3", region_name=REGION)
        client.create_bucket(Bucket="other")
        client.put_object(Bucket="other", Key="deep/key.json", Body=b'{"v": 7}')

        # Base bucket is "artifacts"; a full s3:// ref overrides it verbatim.
        store = ArtifactStore("s3://artifacts/prefix")
        assert await store.load("s3://other/deep/key.json") == {"v": 7}


def test_s3_backend_rejects_traversal():
    store = ArtifactStore("s3://artifacts/prefix", s3_client=object())
    # Resolution happens before any client call, so a dummy client is fine.
    with pytest.raises(ValueError, match=r"must not contain '\.\.'"):
        store._backend._resolve("../escape")  # type: ignore[attr-defined]


def test_s3_base_uri_requires_bucket():
    with pytest.raises(ValueError, match="must include a bucket"):
        ArtifactStore("s3://")
