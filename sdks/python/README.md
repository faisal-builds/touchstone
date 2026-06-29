# Touchstone Python SDK

A typed, synchronous Python client for **Touchstone** — the AI Verification Layer.
Register verifiers, submit AI outputs for verification, and retrieve scores,
uncertainty, and pass/fail decisions in a few lines.

## Install

```bash
pip install touchstone-sdk          # from a package index
# or, from this monorepo:
pip install -e sdks/python
```

## Quickstart

```python
from touchstone import TouchstoneClient

client = TouchstoneClient("http://localhost:8000")

# 1. Bootstrap a tenant (stores the returned JWT on the client)
client.signup(
    email="founder@acme.com",
    password="correct horse battery staple",
    org_name="Acme",
    org_slug="acme",
)

# 2. Create a workspace + project to hold verifiers
ws = client.create_workspace("Research", "research")
project = client.create_project(ws.id, "Coding Agent", "coding-agent")

# 3. Register a verifier — here a deterministic code grader
verifier = client.register_verifier(
    project.id,
    name="Answer Is 42",
    slug="answer-42",
    verifier_type="code",
    definition={
        "code": "def check(artifact):\n    return {'score': 1.0 if artifact.get('answer') == 42 else 0.0}",
        "threshold": 1.0,
    },
)

# 4. Submit an artifact for verification (artifact_ref points at object storage)
run = client.submit_verification(verifier.id, artifact_ref="demo/run-1.json")

# 5. Poll until the verification engine finishes
result = client.wait_for_verification(run.id, timeout=60)
print(result.status, result.score, result.uncertainty, result.passed)
```

## Authentication

Two credential types, both sent as `Authorization: Bearer`:

- **JWT** — obtained from `signup()` / `login()`; the client stores it automatically.
- **API key** — for machine/CI use:

```python
client = TouchstoneClient("http://localhost:8000", api_key="tsk_...")
# or mint one while authenticated as a user:
key = client.create_api_key("ci", role="member")
print(key.secret)   # shown exactly once — store it securely
```

An explicit API key takes precedence over a JWT when both are present.

## Errors

Failures raise typed exceptions parsed from the API's `problem+json` response:

```python
from touchstone import NotFoundError, ConflictError, AuthenticationError

try:
    client.get_verification("00000000-0000-0000-0000-000000000000")
except NotFoundError as e:
    print(e.status, e.detail)   # 404, "Verification run not found."
```

Hierarchy: `TouchstoneError` ← `AuthenticationError` (401), `PermissionDeniedError`
(403), `NotFoundError` (404), `ConflictError` (409), `ValidationError` (422),
`RateLimitError` (429), `APIError` (5xx / other).

## API surface

| Method | Description |
|--------|-------------|
| `signup(...)` / `login(...)` | Authenticate; returns `TokenPair`, stores JWT |
| `create_api_key(name, role=, project_id=)` | Mint an API key (`ApiKeyCreated`) |
| `create_workspace(name, slug)` | Create a workspace |
| `create_project(workspace_id, name, slug)` | Create a project |
| `register_verifier(project_id, name, slug, type, definition)` | Register a verifier (auto-versioned) |
| `submit_verification(verifier_id, artifact_ref)` | Submit an artifact (returns `Verification`, `pending`) |
| `get_verification(id)` | Fetch current state |
| `wait_for_verification(id, timeout=)` | Poll until terminal state |

All methods return typed pydantic models (`from touchstone import Verifier, Verification, ...`).
