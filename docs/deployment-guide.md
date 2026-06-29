# Touchstone Deployment Guide

End-to-end instructions for standing up Touchstone on AWS (EKS). It assumes
familiarity with `kubectl`, `helm`, and `terraform`.

> First time deploying, or validating in a throwaway account? See
> [`live-validation/`](live-validation/README.md) for a step-by-step pre-flight
> checklist, deploy runbook, validation test plan, teardown runbook, and cost
> guardrails built around this exact infrastructure.

## Architecture at a glance

Touchstone runs as seven workloads on EKS — the control-plane API, the
verification / risk / audit engines, the reward-hacking-detector API and its
evaluation worker, and the operator dashboard. State lives in **managed**
datastores outside the cluster: RDS PostgreSQL, ElastiCache Redis, and an MSK /
Kafka-compatible event bus, plus an S3 bucket for verification artifacts. The
chart never deploys a database; it references these via configuration and a
synced secret.

```
  Internet ──▶ ALB (ACM TLS) ──▶ Ingress
                                  ├─▶ control-plane  (api.<domain>)
                                  ├─▶ reward-hacking-detector (robustness.<domain>)
                                  └─▶ web dashboard (app.<domain>)
  workers (no ingress): verification-engine, risk-engine, audit-engine,
                        reward-hacking-detector-worker  ── consume Kafka
  datastores (managed): RDS PostgreSQL · ElastiCache Redis · MSK · S3
```

## Prerequisites

- An AWS account with permissions to create VPC/EKS/RDS/ElastiCache/S3/IAM.
- CLI tools: `terraform >= 1.6`, `kubectl >= 1.27`, `helm >= 3.14`, `aws`.
- A registered domain and a Route 53 hosted zone for it.
- A container registry the cluster can pull from (the release pipeline pushes to
  GHCR; ECR works too).

## 1. Provision infrastructure (Terraform)

```bash
cd deploy/terraform
cp terraform.tfvars.example production.tfvars   # edit region, domain, sizes
terraform init
terraform apply -var-file=production.tfvars
```

This creates the VPC, EKS cluster (with a `general` and a tainted
`sandbox-gvisor` node group), RDS, ElastiCache, S3, the IRSA roles, the ACM
certificate, the KMS keys, and the `touchstone/<env>` Secrets Manager bundle
(seeded with generated JWT/DB/Redis credentials).

Complete ACM validation by creating the DNS records it requests, then capture
the outputs:

```bash
terraform output
```

## 2. Connect and install cluster add-ons

```bash
aws eks update-kubeconfig --name "$(terraform output -raw cluster_name)"
```

Install the operators the chart depends on (once per cluster):

- **AWS Load Balancer Controller** — realizes the ALB `Ingress`.
- **External Secrets Operator** — syncs `touchstone/<env>` from Secrets Manager
  into the `touchstone-secrets` Kubernetes Secret. Create a `ClusterSecretStore`
  named `aws-secrets-manager` annotated with the IRSA role from
  `terraform output -raw irsa_external_secrets_role_arn`.
- **Prometheus Operator (kube-prometheus-stack)** — provides the `ServiceMonitor`
  and `PrometheusRule` CRDs; apply `deploy/observability/`.
- **gVisor (runsc)** — install the `containerd-shim-runsc-v1` on the
  `sandbox-gvisor` nodes (node bootstrap or DaemonSet), then apply the
  `RuntimeClass`: `kubectl apply -f deploy/k8s/30-runtimeclass-gvisor.yaml`.

## 3. Apply namespace scaffolding

```bash
kubectl apply -f deploy/k8s/      # namespace, quotas, priority classes, baseline policy
```

## 4. Wire Terraform outputs into the Helm overlay

Edit `deploy/helm/touchstone/values-production.yaml`, replacing the `REPLACE_…`
markers with:

| Helm value | Terraform output |
|------------|------------------|
| `image.registry` | your registry (e.g. `ghcr.io/<org>`) |
| `externalServices.postgresHost` | `rds_endpoint` |
| `externalServices.redisHost` | `elasticache_endpoint` |
| `externalServices.kafkaBrokers` | MSK bootstrap brokers |
| `externalServices.artifactStoreUri` | `s3://$(terraform output -raw artifact_bucket)` |
| `serviceAccount.annotations` (role-arn) | `irsa_app_role_arn` |
| `ingress.tls.certificateArn` | `acm_certificate_arn` |
| `secrets.externalSecretRemoteKey` | `secrets_manager_key` |

## 5. Deploy

```bash
helm upgrade --install touchstone deploy/helm/touchstone \
  -n touchstone -f deploy/helm/touchstone/values-production.yaml \
  --wait --timeout 10m --atomic
```

In CI this is done by `.github/workflows/release.yml` on a `vX.Y.Z` tag, which
also builds/pushes images and the chart, and gates the deploy behind a
`production` environment approval.

## 6. Database migrations

After the per-service-database split there are three schema owners, each with its
own Alembic history. Run all three once per release, before or during rollout:

```bash
# Control-plane schema: orgs, projects, verifiers (incl. robustness_score),
# verification_runs. Shared by control-plane, verification-engine, risk-engine.
kubectl -n touchstone exec deploy/touchstone-control-plane -- \
  alembic upgrade head

# Reward-hacking-detector schema: robustness_evaluations, exploits, and the
# verifier_refs replica — owned and migrated independently by the RHD image.
kubectl -n touchstone exec deploy/touchstone-reward-hacking-detector -- \
  alembic upgrade head

# Audit-engine schema: audit_records — owned and migrated independently. The
# control-plane reads this table read-only via TOUCHSTONE_AUDIT_DATABASE_URL.
kubectl -n touchstone exec deploy/touchstone-audit-engine -- \
  alembic upgrade head
```

The RHD and audit databases are fed at runtime by events (no cross-database
foreign keys). The audit-engine reads nothing from the control-plane, so its
database can be fully isolated; the control-plane reaches it only through the
read-only audit connection. See the operations guide for the data-flow.

> Auth note: RHD validates `tsk_` API keys by calling the control-plane's
> introspection endpoint (`TOUCHSTONE_RHD_CONTROL_PLANE_URL`, wired by the chart
> to the in-cluster control-plane Service) authenticated with a short-lived
> service token; it reads no control-plane tables, so its database can be fully
> isolated. The endpoint `/v1/internal/auth/introspect` is service-token
> protected; keep it off the public ingress (internal Service / NetworkPolicy
> only) as defense in depth.

## 7. Verify

```bash
kubectl -n touchstone get pods
kubectl -n touchstone rollout status deploy/touchstone-control-plane
kubectl -n touchstone port-forward svc/touchstone-control-plane 8000:8000 &
curl -fsS localhost:8000/readyz | jq
```

Point Route 53 records for `api`, `robustness`, and `app` subdomains at the ALB,
then browse `https://app.<domain>`.

## Rollback

`helm` keeps release history; roll back atomically:

```bash
helm -n touchstone history touchstone
helm -n touchstone rollback touchstone <REVISION> --wait
```

Because Deployments use `RollingUpdate` with `maxUnavailable: 0`, a bad image
never takes capacity offline; `--atomic` auto-rolls-back a failed upgrade.
