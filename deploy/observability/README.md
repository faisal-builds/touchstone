# Observability

Touchstone services emit:

- **Prometheus metrics** at `/metrics` on every HTTP service. Custom HTTP metrics
  (`touchstone_http_requests_total`, `touchstone_http_request_duration_seconds`)
  plus the standard `process_*` / `python_*` collectors. Scraping is wired by the
  `ServiceMonitor` objects in the Helm chart.
- **OpenTelemetry traces** exported via OTLP when `otelExporterOtlpEndpoint` is set
  (no-op otherwise).
- **Structured JSON logs** (structlog) with request/trace correlation IDs.

## Contents

| File | Purpose |
|------|---------|
| `prometheus/alerts.yaml` | `PrometheusRule` — availability, HTTP error-rate/latency, and saturation alerts. |
| `grafana/touchstone-overview.json` | Platform overview dashboard (request rate, error ratio, p95 latency, CPU/memory). |

## Install

```bash
# Alerts (Prometheus Operator):
kubectl apply -f deploy/observability/prometheus/alerts.yaml -n monitoring

# Grafana dashboard: import the JSON, or provision via a ConfigMap labelled
# grafana_dashboard=1 if you use the Grafana sidecar.
kubectl create configmap touchstone-overview \
  --from-file=deploy/observability/grafana/touchstone-overview.json -n monitoring
kubectl label configmap touchstone-overview grafana_dashboard=1 -n monitoring
```

Some alerts (`TouchstonePodCrashLooping`, `TouchstoneHpaMaxedOut`) rely on
**kube-state-metrics** being present in the cluster.
