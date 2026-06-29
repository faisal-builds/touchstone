# @touchstone/sdk

Official **TypeScript SDK** for [Touchstone](../../README.md) — the AI
Verification Layer. A single typed client over both backend services: the
**control-plane** (auth, tenancy, the verifier registry, verifications, audit)
and the **reward-hacking-detector** (robustness evaluations and the exploit
corpus).

- Strict TypeScript, full request/response types, IDE autocompletion.
- Dual **ESM + CommonJS** builds with bundled `.d.ts`.
- **Zero runtime dependencies** — uses the platform `fetch` (Node ≥ 18 and
  modern browsers).
- Typed error hierarchy mapped from RFC-7807 `problem+json`.
- Built-in polling helpers for verifications and robustness evaluations.

## Install

```bash
npm install @touchstone/sdk
```

## Quickstart

```ts
import { TouchstoneClient } from "@touchstone/sdk";

const client = new TouchstoneClient({ baseUrl: "http://localhost:8000" });

// Create an org + owner; the JWT is stored on the client automatically.
await client.signup({
  email: "founder@acme.com",
  password: "correct horse battery staple",
  orgName: "Acme",
  orgSlug: "acme",
});

// Mint a machine credential and switch to it.
const key = await client.createApiKey("ci", { role: "member" });
client.setApiKey(key.secret); // the plaintext secret is shown exactly once

const ws = await client.createWorkspace("Research", "research");
const project = await client.createProject(ws.id, "Coding Agent", "coding-agent");

const verifier = await client.registerVerifier(
  project.id,
  "Answer 42",
  "answer-42",
  "code",
  {
    code: "def check(a):\n return {'score': 1.0 if a.get('answer') == 42 else 0.0}",
    threshold: 1.0,
  },
);

const run = await client.submitVerification(verifier.id, "s3://bucket/output.json");
const result = await client.waitForVerification(run.id);
console.log(result.status, result.score, result.passed, result.risk_score);
```

A runnable version of this flow is in [`examples/demo.ts`](./examples/demo.ts)
(`npm run demo` against a live stack).

## Authentication

The client sends `Authorization: Bearer <credential>`. The credential is either
an **API key** or a **user JWT**; if both are set, the API key wins.

```ts
// From an API key:
const client = new TouchstoneClient({ baseUrl, apiKey: "tsk_..." });

// Or from signup/login (stores the JWT):
await client.login({ email: "me@acme.com", password: "..." });

// Swap credentials at any time:
client.setApiKey("tsk_...");
client.setToken("eyJ...");
client.credential; // the active bearer value, or undefined
```

The reward-hacking-detector accepts the same credential. If it runs on a separate
host, pass `rhdUrl`:

```ts
const client = new TouchstoneClient({
  baseUrl: "https://api.touchstone.example.com",
  rhdUrl: "https://robustness.touchstone.example.com",
});
```

## API surface

**Auth** — `signup`, `login`
**API keys** — `createApiKey`, `listApiKeys`, `revokeApiKey`
**Workspaces** — `createWorkspace`, `listWorkspaces`, `getWorkspace`
**Projects** — `createProject`, `listProjects`
**Verifiers** — `registerVerifier`, `listVerifiers`, `getVerifier`, `deleteVerifier`
**Verifications** — `submitVerification`, `getVerification`, `listVerifications`, `waitForVerification`
**Audit** — `listAudit`
**Robustness (RHD)** — `launchEvaluation`, `getEvaluation`, `getEvaluationReport`, `listVerifierEvaluations`, `listVerifierExploits`, `getVerifierTrend`, `compareEvaluations`, `searchExploits`, `waitForEvaluation`
**Health** — `health`, `ready`

Every method returns a fully-typed model (see the exported interfaces such as
`Verifier`, `Verification`, `Evaluation`, `Exploit`).

### Robustness example

```ts
const evaluation = await client.launchEvaluation(verifier.id, { enableModelAttacks: true });
const done = await client.waitForEvaluation(evaluation.id);
console.log(done.robustness_score, done.weighted_robustness_score, done.ci);

const report = await client.getEvaluationReport(done.id);
console.log(report.category_counts, report.exploits.length);

// Search the exploit corpus:
const exploits = await client.searchExploits({
  verifierId: verifier.id,
  severity: "high",
  q: "prompt injection",
});
```

## Error handling

Failures throw a typed subclass of `TouchstoneError`, parsed from the API's
`problem+json` body. Each carries `status`, `detail`, `typeUri`, and the raw
`body`.

```ts
import {
  NotFoundError,
  ConflictError,
  RateLimitError,
  AuthenticationError,
} from "@touchstone/sdk";

try {
  await client.getVerifier(projectId, "missing");
} catch (err) {
  if (err instanceof NotFoundError) {
    // 404
  } else if (err instanceof ConflictError) {
    // 409 — duplicate slug/email
  } else if (err instanceof RateLimitError) {
    console.log("retry after", err.retryAfter, "seconds");
  } else if (err instanceof AuthenticationError) {
    // 401
  } else {
    throw err;
  }
}
```

| Status | Error |
|--------|-------|
| 401 | `AuthenticationError` |
| 403 | `PermissionDeniedError` |
| 404 | `NotFoundError` |
| 409 | `ConflictError` |
| 422 | `ValidationError` |
| 429 | `RateLimitError` (with `retryAfter`) |
| 5xx / other | `ApiError` |

The `waitFor*` helpers throw `PollTimeoutError` when their deadline elapses.

## Polling

```ts
// Defaults: verification 60s @ 500ms, evaluation 120s @ 1000ms.
const result = await client.waitForVerification(run.id, {
  timeoutMs: 30_000,
  intervalMs: 1_000,
  signal: AbortSignal.timeout(45_000), // optional cancellation
});
```

## Configuration

```ts
new TouchstoneClient({
  baseUrl,      // control-plane URL (default http://localhost:8000)
  rhdUrl,       // RHD URL (default = baseUrl)
  apiKey,       // or
  token,
  timeoutMs,    // per-request timeout (default 30000)
  fetch,        // custom fetch (testing / non-standard runtimes)
});
```

## Development

```bash
npm install
npm run build       # dual ESM + CJS + .d.ts (tsup)
npm run typecheck   # tsc --noEmit, strict
npm run lint        # eslint, zero warnings
npm test            # vitest
```

## Compatibility

The SDK mirrors the same backend contracts as the Python SDK and the operator
dashboard, generated from the control-plane's OpenAPI 3.1 spec. It targets Node
≥ 18 (for global `fetch`) and any modern browser bundler.
