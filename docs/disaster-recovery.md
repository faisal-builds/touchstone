# Touchstone Disaster Recovery

How Touchstone's data is protected and how to recover from failures. Pair this
with the operations guide for day-2 procedures.

## What is backed up

| Asset | Mechanism | Retention | Configured in |
|-------|-----------|-----------|---------------|
| PostgreSQL (RDS) | Automated daily backups + transaction logs (PITR) | 14 days | `modules/rds` (`backup_retention_period = 14`) |
| PostgreSQL | Final snapshot on destroy | until deleted | `modules/rds` (`final_snapshot_identifier`) |
| Redis (ElastiCache) | Daily snapshots | 7 days | `modules/elasticache` (`snapshot_retention_limit = 7`) |
| Artifacts (S3) | Versioning + 90-day noncurrent retention | 90 days | `modules/s3` |
| Secrets | AWS Secrets Manager (versioned) | per-secret | root `aws_secretsmanager_secret` |
| Infra definition | Terraform state in S3 (versioned) + DynamoDB lock | indefinite | `versions.tf` backend |

Redis holds only ephemeral rate-limiter state, so it is **not** on the critical
recovery path — it can be recreated empty. The authoritative state is
PostgreSQL (tenancy, verifiers, verification results, the per-org audit hash
chain) and S3 (artifacts).

## Objectives

| Tier | RPO (data loss) | RTO (time to restore) |
|------|-----------------|------------------------|
| PostgreSQL | ≤ 5 min (PITR) | ≤ 1 hour |
| S3 artifacts | ≈ 0 (versioned, multi-AZ) | minutes |
| Full region loss | ≤ 24 h (snapshot copy) | ≤ 4 hours |

These are design targets; validate them in the DR drills below.

## Failure scenarios

### Single AZ failure
No action required. The VPC spans 3 AZs; RDS is multi-AZ (synchronous standby),
ElastiCache has multi-AZ automatic failover, and EKS node groups span AZs.
Kubernetes reschedules pods onto healthy AZs; PodDisruptionBudgets keep a
replica serving.

### RDS instance failure
Multi-AZ promotes the standby automatically (typically 60–120s). The endpoint
is unchanged, so pods reconnect via `pool_pre_ping`. No manual step.

### Data corruption / accidental data loss (PITR)
Restore to a new instance at a timestamp just before the incident:

```bash
aws rds restore-db-instance-to-point-in-time \
  --source-db-instance-identifier touchstone-production \
  --target-db-instance-identifier touchstone-recovery \
  --restore-time 2026-06-28T11:55:00Z
```

Validate the restored data, then cut over by pointing
`externalServices.postgresHost` at the recovered endpoint (update the DB URL in
Secrets Manager and `helm upgrade`). Because the audit log is a per-org hash
chain, run `audit-engine verify` after restore to confirm chain integrity.

### Accidental S3 object deletion
Versioning is enabled; delete markers can be removed to restore the prior
version. Noncurrent versions persist 90 days.

### EKS cluster loss
The cluster is cattle, not pets — nothing stateful lives in it. Recreate it:

```bash
cd deploy/terraform && terraform apply -var-file=production.tfvars
aws eks update-kubeconfig --name "$(terraform output -raw cluster_name)"
kubectl apply -f deploy/k8s/
# reinstall add-ons (LB controller, ESO, Prometheus operator, runsc), then:
helm upgrade --install touchstone deploy/helm/touchstone -n touchstone \
  -f deploy/helm/touchstone/values-production.yaml --wait --atomic
```

The datastores (RDS/ElastiCache/S3) are separate Terraform resources and are
untouched by a cluster rebuild.

### Secrets Manager value loss / compromise
Secrets are versioned; recover a prior version with
`aws secretsmanager get-secret-value --version-stage AWSPREVIOUS`. On
compromise, rotate (see operations guide) — regenerate via `terraform apply`,
let ESO re-sync, and roll the workloads.

### Full region outage
1. Recreate infra in a secondary region: `terraform apply` with a region-scoped
   var file (use a copied RDS snapshot — enable cross-region automated-backup
   replication or copy the latest snapshot as part of drills).
2. Restore RDS from the latest cross-region snapshot.
3. Re-point DNS (Route 53) at the new region's ALB.

RPO here is bounded by snapshot-copy frequency; for tighter RPO add an RDS
cross-region read replica and promote it.

## Terraform state recovery
State is in a versioned S3 bucket with a DynamoDB lock table. If state is
corrupted, restore the prior S3 object version. Never edit state by hand; use
`terraform state` subcommands. A stuck lock is cleared with
`terraform force-unlock <LOCK_ID>` after confirming no apply is in flight.

## DR drills (run quarterly)

1. **PITR restore**: restore RDS to a new instance from a timestamp; verify row
   counts and audit-chain integrity; tear down. Confirm RTO ≤ 1h.
2. **Cluster rebuild**: in staging, `terraform destroy` the EKS module only and
   recreate; redeploy via Helm; confirm the platform comes up against the
   untouched datastores.
3. **Secret rotation**: rotate the JWT secret end-to-end and confirm clients
   re-authenticate cleanly.

Record actual RPO/RTO from each drill and adjust capacity or backup frequency if
targets are missed.
