# Cost Guardrails — Live AWS Validation

All figures are **approximate**, `us-east-1`, on-demand, and meant for planning,
not billing. Verify with the [AWS Pricing Calculator](https://calculator.aws).
The single most effective guardrail is **time**: destroy the environment the same
day. A half-day lean validation is ~$7–9 total.

---

## Expected cost — stock Terraform defaults

The committed defaults are **production-sized**. Per-component, roughly:

| Component | Default | ~$/hour | ~$/day |
|---|---|---|---|
| EKS control plane | 1 cluster | 0.10 | 2.40 |
| General nodes | 3 × m6i.large | ~0.29 | ~6.9 |
| Sandbox nodes | 2 × m6i.xlarge | ~0.38 | ~9.2 |
| RDS PostgreSQL | db.r6g.large, **multi-AZ** | ~0.48 | ~11.5 |
| RDS storage | 100 GiB gp3 | ~0.01 | ~0.3 |
| ElastiCache | cache.r6g.large × **2** | ~0.41 | ~9.9 |
| NAT gateways | 3 (one per AZ) + data | ~0.14+ | ~3.5 |
| ALB | 1 + LCUs | ~0.03 | ~0.7 |
| S3 / KMS / Secrets / logs | minimal | — | ~1–2 |
| **Total (defaults)** | | **~1.9–2.3** | **~45–55** |

- **1 day (defaults): ~$45–55.**
- **1 week (defaults): ~$320–380.**

> Add **MSK** only if you choose it over in-cluster Redpanda: 3 × kafka.m5.large
> ≈ **$15/day** extra. For validation, use Redpanda (no extra AWS charge).

## Expected cost — lean validation config (recommended)

| Component | Lean | ~$/day |
|---|---|---|
| EKS control plane | 1 cluster | 2.40 |
| General nodes | 2 × t3.large | ~4.0 |
| Sandbox nodes | 1 × m6i.large | ~2.3 |
| RDS | db.t4g.medium, **single-AZ**, 20 GiB | ~1.6 |
| ElastiCache | cache.t4g.micro, **1 node** | ~0.4 |
| NAT gateways | 2 (2 AZs) | ~2.2 |
| ALB | 1 | ~0.7 |
| misc | S3/KMS/Secrets | ~1 |
| **Total (lean)** | | **~13–18/day** |

- **1 day (lean): ~$13–18.**
- **1 week (lean): ~$95–125.**

### Applying the lean config

**Via `validation.tfvars`** (variabilized knobs):

```hcl
environment                = "validation"
availability_zone_count    = 2
postgres_instance_class    = "db.t4g.medium"
postgres_allocated_storage = 20
redis_node_type            = "cache.t4g.micro"
domain_name                = "validation.yourdomain.com"
```

**Via small module edits** (node sizes + RDS HA are hardcoded). Make these, apply,
and **`git checkout` them after teardown** so you don't commit throwaway sizing:

- `modules/eks/main.tf`:
  - general node group: `instance_types = ["t3.large"]`, `desired_size = 2`,
    `min_size = 2`.
  - sandbox node group: `instance_types = ["m6i.large"]`, `desired_size = 1`,
    `min_size = 1`. (Keep an m-class for runsc headroom; t3 works for light tests.)
- `modules/rds/main.tf`: `multi_az = false`. (Optionally
  `backup_retention_period = 1` to shrink backups.)
- `modules/elasticache/main.tf`: `num_cache_clusters = 1`,
  `automatic_failover_enabled = false`, `multi_az_enabled = false`.

> ElastiCache `transit_encryption_enabled = true` requires TLS from clients; leave
> encryption on (the app supports `rediss://`). Don't disable it to "simplify".

## Services that can accidentally become expensive

- **NAT gateways** — one per AZ by default (3). They bill hourly **and** per GB
  processed. Reducing `availability_zone_count` to 2 saves one. The biggest
  surprise is leaving them running after a failed teardown.
- **RDS multi-AZ** — doubles instance cost; r6g.large multi-AZ is ~$11/day for a
  test. Use single-AZ + t4g for validation.
- **ElastiCache 2-node** — doubles node cost; use a single t4g.micro.
- **Sandbox node pool** — m6i.xlarge × 2 is the priciest compute line. One node is
  plenty for validation.
- **EKS node-group autoscaling** — max sizes are 10 (general) and **20** (sandbox).
  A runaway load/stress test could scale the sandbox pool up. Cap it: set
  `max_size` low in the module for validation, or run only the `staging` (not
  `stress`) load profile.
- **MSK** — if chosen, ~$15/day for 3 brokers; avoid for validation.
- **Orphaned ALB / EIPs / RDS snapshots / PendingDeletion KMS keys** — the classic
  post-teardown leaks. The teardown "confirm destroyed" list catches them.
- **Data egress** — large load tests pull data through NAT/ALB; modest for a short
  run but non-zero.

## How to set AWS budgets and alerts (do this BEFORE apply)

**a) A daily budget with an alert** (replace the email):

```bash
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
cat > /tmp/budget.json <<EOF
{ "BudgetName": "touchstone-validation-daily",
  "BudgetLimit": { "Amount": "20", "Unit": "USD" },
  "TimeUnit": "DAILY", "BudgetType": "COST" }
EOF
cat > /tmp/notify.json <<EOF
[ { "Notification": { "NotificationType": "ACTUAL", "ComparisonOperator": "GREATER_THAN",
      "Threshold": 80, "ThresholdType": "PERCENTAGE" },
    "Subscribers": [ { "SubscriptionType": "EMAIL", "Address": "you@example.com" } ] } ]
EOF
aws budgets create-budget --account-id "$ACCOUNT" \
  --budget file:///tmp/budget.json --notifications-with-subscribers file:///tmp/notify.json
```

**b) Cost Anomaly Detection** (free) — create a monitor for the account:

```bash
aws ce create-anomaly-monitor --anomaly-monitor \
  '{"MonitorName":"touchstone-validation","MonitorType":"DIMENSIONAL","MonitorDimension":"SERVICE"}'
```

**c) A billing-estimate CloudWatch alarm** (us-east-1 only carries the billing
metric):

```bash
aws cloudwatch put-metric-alarm --alarm-name touchstone-bill-50 \
  --namespace AWS/Billing --metric-name EstimatedCharges \
  --dimensions Name=Currency,Value=USD --statistic Maximum --period 21600 \
  --threshold 50 --comparison-operator GreaterThanThreshold \
  --evaluation-periods 1 --region us-east-1
```

Also set a **calendar reminder** to tear down; automation won't save you from a
forgotten cluster.

## How to confirm everything was destroyed

After `TEARDOWN_RUNBOOK.md`, run its "confirm everything was destroyed" block.
The essentials, each must be empty:

```bash
aws eks list-clusters --query clusters --output text
aws rds describe-db-instances --query "DBInstances[].DBInstanceIdentifier" --output text
aws elasticache describe-replication-groups --query "ReplicationGroups[].ReplicationGroupId" --output text
aws ec2 describe-nat-gateways --filter Name=state,Values=available --query 'NatGateways[].NatGatewayId' --output text
aws ec2 describe-addresses --query 'Addresses[].PublicIp' --output text     # leftover EIPs
aws elbv2 describe-load-balancers --query "LoadBalancers[?contains(LoadBalancerName,'k8s')].LoadBalancerName" --output text
aws s3 ls | grep touchstone || echo "no buckets"
aws rds describe-db-snapshots --snapshot-type manual --query "DBSnapshots[?contains(DBSnapshotIdentifier,'touchstone')].DBSnapshotIdentifier" --output text
```

Then, the next day:

1. **Billing → Cost Explorer**, group by service: confirm EKS/EC2/RDS/ElastiCache
   spend drops to ~0.
2. Expect small **residual** charges for: NAT/EBS partial-hour usage already
   incurred, KMS keys in `PendingDeletion` (~$1/key/mo until the window closes),
   and any retained snapshot you chose to keep. These are expected; everything
   else should be gone.
3. If the daily budget alert fires after teardown, something is still running —
   re-run the confirmation list and the orphaned-ALB/EIP checks.

For maximum certainty in a throwaway Organization account, you can also **close
the member account** once Cost Explorer confirms ~zero spend.
