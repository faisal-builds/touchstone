# Touchstone Operations Guide

Day-2 operations for a running Touchstone deployment.

## Observability

- **Metrics**: every HTTP service exposes `/metrics`; `ServiceMonitor`s scrape
  them. Key series: `touchstone_http_requests_total`,
  `touchstone_http_request_duration_seconds`, and the standard `process_*`.
- **Dashboards**: import `deploy/observability/grafana/touchstone-overview.json`.
- **Alerts**: `deploy/observability/prometheus/alerts.yaml` (service down, 5xx
  rate, p95 latency, crash-looping, HPA maxed out).
- **Traces**: set `config.otelExporterOtlpEndpoint` to your collector; spans are
  emitted by the FastAPI services.
- **Logs**: structured JSON via structlog; every line carries `request_id` and,
  where available, `trace_id`. Query by those to follow a request across
  services.

## Scaling

Stateless services scale via HPA (`autoscaling` block per service in
`values.yaml`). To change bounds:

```bash
helm upgrade touchstone deploy/helm/touchstone -n touchstone \
  -f deploy/helm/touchstone/values-production.yaml \
  --set services.verification-engine.autoscaling.maxReplicas=40
```

If `TouchstoneHpaMaxedOut` fires for a sustained period, raise `maxReplicas`
and/or the node group's `max_size` (Terraform). Datastores scale independently:
RDS instance class / storage and ElastiCache node type are Terraform variables.

## Load & performance testing

The Locust suite under `load-tests/` measures the verification hot path and the
surrounding API surface. Use it to establish a pre-release baseline and to size
capacity before a launch or after a major change.

```bash
pip install -e load-tests
cd load-tests
# Steady-state against staging (worker + broker present, so completion and
# worker-throughput gates are enforced):
TOUCHSTONE_LOAD_HOST="https://api.staging.touchstone.example.com" \
TOUCHSTONE_LOAD_RHD_URL="https://robustness.staging.touchstone.example.com" \
TOUCHSTONE_LOAD_ENABLE_RHD=true \
TOUCHSTONE_LOAD_ARTIFACT_REF="s3-key/of/a/real/artifact.json" \
./run.sh staging        # or: stress
```

Run against an **isolated** environment (never production tenants): the suite
creates real orgs, users, keys, verifiers, and verification runs. The
`staging`/`stress` profiles fail the run on excessive p95/p99, error rate,
verification-poll timeout rate, or completion time; tune the gates per
environment with the `TOUCHSTONE_LOAD_MAX_*` variables. Watch the broker/worker
Prometheus metrics during the run for queue backlog and worker throughput —
those are measured server-side, not by the client. See `load-tests/README.md`
for profiles, metrics, and the limitations of non-live numbers.


## Secret rotation

Secrets live in AWS Secrets Manager (`touchstone/<env>`) and are synced by the
External Secrets Operator. To rotate the JWT signing secret or a datastore
credential:

1. Update the value in Secrets Manager (or `terraform apply` to regenerate the
   `random_password` and push it).
2. ESO re-syncs within its `refreshInterval` (1h); force it sooner by deleting
   the managed `Secret` (ESO recreates it) or annotating the `ExternalSecret`.
3. Restart consumers to pick up the new value:
   `kubectl -n touchstone rollout restart deploy -l app.kubernetes.io/name=touchstone`.

JWTs are HS256; rotating the secret invalidates outstanding access tokens —
expected, and clients simply re-authenticate.

## Sandbox / gVisor operations

Verifier code runs in gVisor (`runsc`) on the `sandbox-gvisor` node group.

- Confirm the runtime is registered: on a sandbox node,
  `runsc --version` and `ctr plugin ls | grep runsc`.
- The verification engine is configured with `sandboxAllowFallback: "false"` in
  production — if the runtime is missing the worker fails loudly rather than
  silently dropping to the subprocess backend. If you see
  `SandboxRuntimeUnavailable` in logs, the node's `runsc` shim is missing or the
  `RuntimeClass` is not applied.
- To roll the sandbox image, bump `config.sandboxImage` and `helm upgrade`.

## Event-stream runbooks

**Consumer lag.** Check lag per group on the Kafka/MSK side. Lag growth on
`touchstone.verification.v1` usually means the verification engine is saturated
— the HPA should scale it on CPU; if pinned at max, raise the ceiling.

**Dead-letter queue.** Messages that fail envelope validation are routed to
`<topic>.dlq` (e.g. `touchstone.verification.v1.dlq`) with the original bytes
(base64), the error, and source partition/offset. To inspect:

```bash
kcat -b "$BROKERS" -t touchstone.verification.v1.dlq -C -o beginning -e | jq
```

Each record carries `payload_b64`; decode it to recover the original message for
replay after fixing the producer/schema. A growing DLQ indicates a producer bug
or a schema mismatch, not a transient error (transient processing failures are
recorded on the verification row instead, via `mark_failed`).

## Runbook: elevated 5xx rate

1. Identify the service from the `TouchstoneHighErrorRate` alert's `job` label.
2. Check `/readyz` — a degraded datastore check points at RDS/Redis/Kafka.
3. Inspect recent logs filtered to `status >= 500`; the structured `error` field
   and `trace_id` localize the failure.
4. If a bad release: `helm rollback` (see deployment guide). `--atomic` upgrades
   self-roll-back, so a manual rollback is mainly for issues found post-deploy.

## Upgrades

- **Application**: tag `vX.Y.Z`; the release pipeline builds, publishes, and
  (after approval) deploys. Run Alembic migrations as part of the release.
- **Kubernetes**: bump `cluster_version` in Terraform; upgrade the control plane
  then node groups (rolling). PodDisruptionBudgets (`minAvailable: 1`) keep a
  replica serving during node drains.
- **TLS certificate**: ACM auto-renews DNS-validated certs; no action if the
  validation records remain in place.

## Capacity & cost levers

- Per-AZ NAT gateways and multi-AZ RDS/Redis are the main fixed costs; reduce
  `availability_zone_count` in non-prod.
- Worker node groups (`sandbox-gvisor`, `general`) scale on demand; set sensible
  `max_size` to bound spend.
