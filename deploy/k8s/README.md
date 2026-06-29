# Kubernetes manifests

Touchstone is deployed with the **Helm chart** in [`../helm/touchstone`](../helm/touchstone),
which is the source of truth for all per-release workloads — Deployments,
Services, ConfigMap, Secret/ExternalSecret, HorizontalPodAutoscalers,
PodDisruptionBudgets, Ingress, ServiceMonitors, and NetworkPolicies. Every
service gets its own Deployment with explicit resource requests/limits and a
hardened security context (non-root, read-only root filesystem, all capabilities
dropped, seccomp `RuntimeDefault`).

The manifests in **this** directory are cluster/namespace scaffolding that is
deliberately *not* part of the release chart, because it has a different
lifecycle (it is applied once per cluster, by a platform admin, before the chart
is installed):

| File | Purpose |
|------|---------|
| `00-namespace.yaml` | Creates the `touchstone` namespace and pins the **restricted** Pod Security Standard. |
| `10-resource-governance.yaml` | `ResourceQuota` + `LimitRange` guardrails for the namespace. |
| `20-priorityclasses.yaml` | `PriorityClass`es for latency-sensitive services vs throughput workers. |
| `30-runtimeclass-gvisor.yaml` | The `gvisor` `RuntimeClass` used by sandbox worker pods (ADR-002). |
| `40-baseline-networkpolicy.yaml` | Namespace-wide default-deny baseline; the chart layers explicit allows on top. |

## Apply order

```bash
# 1. Cluster scaffolding (once per cluster, ordered by filename):
kubectl apply -f deploy/k8s/

# 2. The platform (per release):
helm upgrade --install touchstone deploy/helm/touchstone \
  -n touchstone -f deploy/helm/touchstone/values-production.yaml
```

## Rendering raw manifests from the chart

If a GitOps tool (Argo CD, Flux) needs plain manifests rather than a Helm
release, render them:

```bash
helm template touchstone deploy/helm/touchstone \
  -n touchstone -f deploy/helm/touchstone/values-production.yaml > rendered.yaml
```

> Note: this repository was assembled in an environment without `helm`/`kubectl`,
> so the chart and these manifests were validated structurally (YAML parse +
> template control-flow balance) rather than with a live `helm lint` /
> `kubeconform`. Run those in CI (see `.github/workflows/`) before promoting.
