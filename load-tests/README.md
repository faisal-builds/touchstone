# Touchstone load & performance suite

A [Locust](https://locust.io/)-based load suite for the Touchstone V1 backend,
focused on the **verification hot path** (submit → worker → completed) plus the
surrounding control-plane and reward-hacking-detector surfaces. It is the
pre-live baseline: run it locally and in CI as a regression tripwire, and against
a real staging/AWS cluster to get production-representative numbers before the
live validation gate.

## What it exercises

| Scenario | Endpoint(s) |
|---|---|
| Signup / login | `POST /v1/auth/signup`, `POST /v1/auth/login` |
| API key creation | `POST /v1/api-keys` |
| Verifier registration | `POST /v1/projects/{id}/verifiers` |
| **Verification submission** | `POST /v1/verifications` |
| **Polling verification results** | `GET /v1/verifications/{id}` |
| Dashboard reads | `GET /v1/workspaces`, `…/projects`, `…/verifiers`, `/v1/verifications` |
| Audit retrieval | `GET /v1/audit` |
| Robustness evaluation submission | `POST /v1/robustness/evaluations` (opt-in) |
| Exploit search | `GET /v1/robustness/exploits/search` (opt-in) |

The verification hot path is driven by `VerificationHotPathUser`, which submits a
run and polls it to a terminal state, recording submission throughput, poll
latency, end-to-end completion time, and the poll-timeout rate.

## Install

```bash
pip install -e load-tests            # or: pip install locust requests
```

## Run locally

Bring up at least the control-plane (and, for end-to-end completion, the
verification worker + broker). Then:

```bash
cd load-tests
./run.sh local            # or: smoke | staging | stress
```

`run.sh` reads the profile from `touchstone_load/config.py` (the single source of
truth) to set Locust's user count, spawn rate, and duration, then enforces that
profile's thresholds when the run ends (non-zero exit on breach).

Targets and payloads are environment variables:

| Variable | Default | Meaning |
|---|---|---|
| `TOUCHSTONE_LOAD_HOST` | `http://localhost:8000` | control-plane base URL |
| `TOUCHSTONE_LOAD_RHD_URL` | `http://localhost:8030` | reward-hacking-detector base URL |
| `TOUCHSTONE_LOAD_ENABLE_RHD` | `false` | include the RHD scenarios |
| `TOUCHSTONE_LOAD_ARTIFACT_REF` | `load/sample.json` | artifact ref submitted for verification |

## Run against staging / AWS

Point the suite at the cluster's ingress and enable the worker-dependent gates:

```bash
cd load-tests
TOUCHSTONE_LOAD_HOST="https://api.staging.touchstone.example.com" \
TOUCHSTONE_LOAD_RHD_URL="https://robustness.staging.touchstone.example.com" \
TOUCHSTONE_LOAD_ENABLE_RHD=true \
TOUCHSTONE_LOAD_ARTIFACT_REF="s3-key/of/a/real/artifact.json" \
./run.sh staging
```

For the **end-to-end completion** and **worker throughput** numbers to be
meaningful, a verification worker must be draining the queue and the
`artifact_ref` must resolve in the configured artifact store (S3 in production) so
the worker can load it. The `staging`/`stress` profiles set
`expect_completion=true`, so a high timeout rate or slow completion **fails** the
run.

## Profiles

| Profile | Users | Duration | Worker expected | Use |
|---|---|---|---|---|
| `smoke` | 3 | 20s | no | CI tripwire; gross-regression detection |
| `local` | 10 | 1m | no | developer runs on a single node |
| `staging` | 50 | 5m | yes | steady-state against a real cluster |
| `stress` | 300 | 10m | yes | find the knee; looser latency gates |

Override any knob without editing code, e.g. `TOUCHSTONE_LOAD_USERS=25
TOUCHSTONE_LOAD_RUN_TIME=2m ./run.sh local`.

## Metrics

Locust reports per-endpoint RPS and p50/p95/p99 latency and an error rate. The
suite adds the hot-path metrics Locust cannot infer:

- **verification completion time** (`HOTPATH / verification:completed`) — submit →
  terminal state, with its own percentiles;
- **poll timeout rate** — fraction of hot-path verifications that did not reach a
  terminal state within the poll budget;
- **worker throughput** — completed verifications per second (derived);
- **submitted / completed counts** for the run.

A summary block prints at the end with a `RESULT: PASS|FAIL`.

## Pass/fail thresholds

Defaults live in `touchstone_load/config.py` per profile and are all overridable
by environment variable:

| Threshold | Env override |
|---|---|
| max p95 latency (ms) | `TOUCHSTONE_LOAD_MAX_P95_MS` |
| max p99 latency (ms) | `TOUCHSTONE_LOAD_MAX_P99_MS` |
| max error rate (0..1) | `TOUCHSTONE_LOAD_MAX_ERROR_RATE` |
| max poll-timeout rate (0..1) | `TOUCHSTONE_LOAD_MAX_TIMEOUT_RATE` |
| max completion p95 (ms) | `TOUCHSTONE_LOAD_MAX_COMPLETION_MS` |

A breach sets a non-zero exit code so CI fails the job.

## Interpreting results

- **error rate > 0** in `smoke`/`local` almost always means a wiring problem
  (wrong host, missing migration, unseeded dependency), not a performance issue.
- **High p95 with low median** on the auth scenarios is expected: Argon2id
  password/key hashing is deliberately CPU-heavy. Watch it as a capacity signal,
  not a bug — size CPU accordingly.
- **timeout rate near 1.0 locally** is normal: there is no worker, so nothing
  completes. It is only enforced under `staging`/`stress`.
- For the hot path, the numbers that matter for capacity planning are
  **submission RPS**, **completion p95**, and **worker throughput** — and those
  are only real with a worker + broker behind the API.

## Known limitations (sandbox numbers are not production numbers)

- Numbers from a single dev box or CI runner are **indicative, not
  production-representative**. They share a host with the services, the database,
  and Locust itself; there is no network, no autoscaling, and no managed
  datastore behavior. Treat them as relative/regression signals.
- Without a broker + worker (the default local/CI setup), **end-to-end
  completion, worker throughput, and queue backlog cannot be measured** — the
  suite measures the API hot path (submission + poll latency) and explicitly does
  not fail on non-completion in those profiles.
- The gVisor/Firecracker sandbox cost per verification is only realistic on a
  runtime-equipped node; on a dev box the subprocess baseline is used, which is
  faster than production isolation.
- Queue/backlog growth is best measured from the broker/worker metrics
  (Prometheus) during a `staging`/`stress` run, not from the client side.

The authoritative numbers come from running `staging`/`stress` against a real
cluster during live validation.
