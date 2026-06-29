# Teardown Runbook — Destroy the Validation Environment

Run this **the same day** as the deploy. Order matters: tear down the
chart-created cloud resources (ALB) first, then Terraform, then the manual
leftovers (DNS, state, snapshots). The three things that **will block**
`terraform destroy` if you skip them are called out explicitly — handle them
**before** running destroy.

Sanity gate:

```bash
aws sts get-caller-identity --query Account --output text   # MUST be the throwaway account
cd deploy/terraform
```

---

## Step 1 — Helm uninstall (releases the ALB + in-cluster resources)

```bash
helm -n touchstone uninstall touchstone
# Wait for the AWS LB Controller to delete the ALB it created from the Ingress:
kubectl -n touchstone get ingress 2>/dev/null    # should become empty
```

Then remove the cluster add-ons and scaffolding (so nothing recreates AWS
resources during destroy):

```bash
helm -n redpanda uninstall redpanda || true
helm -n monitoring uninstall kube-prometheus-stack || true
helm -n external-secrets uninstall external-secrets || true
# Uninstall the AWS Load Balancer Controller LAST among controllers, and confirm
# no ALBs/target groups remain (it owns their lifecycle):
helm -n kube-system uninstall aws-load-balancer-controller || true
kubectl delete -f deploy/k8s/ || true
```

**Verify no orphaned load balancer** (a common leak that keeps costing money):

```bash
aws elbv2 describe-load-balancers \
  --query "LoadBalancers[?contains(LoadBalancerName,'touchstone') || contains(LoadBalancerName,'k8s')].LoadBalancerArn" \
  --output text
# If any remain, delete them, plus their target groups and any leftover SGs.
```

## Step 2 — Clear the three Terraform destroy blockers

### 2a. RDS deletion protection + final snapshot

RDS is created with `deletion_protection = true` and `skip_final_snapshot =
false`. `terraform destroy` will fail until you resolve both. Choose one:

**Option A — keep a final snapshot (default behavior):** just disable deletion
protection; destroy will then create `touchstone-validation-final` automatically.
You must delete that snapshot afterward (Step 5) or it lingers (small cost).

```bash
RDS_ID=$(terraform state show 'module.rds.aws_db_instance.this' | awk '/identifier /{print $3; exit}' | tr -d '"')
aws rds modify-db-instance --db-instance-identifier "$RDS_ID" \
  --no-deletion-protection --apply-immediately
aws rds wait db-instance-available --db-instance-identifier "$RDS_ID"
```

**Option B — skip the final snapshot (nothing to clean up later):** edit
`deploy/terraform/modules/rds/main.tf`, set `deletion_protection = false` and
`skip_final_snapshot = true`, then `terraform apply -var-file=validation.tfvars`
once to push those settings before destroy. (Remember to `git checkout` the
module afterward.)

### 2b. Empty the versioned S3 artifact bucket

The artifact bucket has versioning enabled and **no** `force_destroy`, so destroy
fails while any object/version/delete-marker remains. Empty it completely:

```bash
BUCKET=$(terraform output -raw artifact_bucket)
aws s3 rm "s3://$BUCKET" --recursive
# Purge versions + delete markers:
aws s3api list-object-versions --bucket "$BUCKET" \
  --query '{Objects: Versions[].{Key:Key,VersionId:VersionId}}' --output json > /tmp/v.json
aws s3api delete-objects --bucket "$BUCKET" --delete file:///tmp/v.json 2>/dev/null || true
aws s3api list-object-versions --bucket "$BUCKET" \
  --query '{Objects: DeleteMarkers[].{Key:Key,VersionId:VersionId}}' --output json > /tmp/d.json
aws s3api delete-objects --bucket "$BUCKET" --delete file:///tmp/d.json 2>/dev/null || true
```

### 2c. (Awareness) Secrets Manager recovery window

`terraform destroy` schedules the `touchstone/<env>` secret for deletion with a
recovery window (it is not purged immediately). That's fine — it's free-tier
small and auto-deletes. Step 4 force-deletes it if you want the name freed now.

## Step 3 — Terraform destroy

```bash
terraform destroy -var-file=validation.tfvars
```

This removes EKS (+ node groups), VPC (+ NAT gateways + EIPs), RDS, ElastiCache,
S3 bucket, IAM/IRSA roles, ACM cert, KMS aliases, and schedules the KMS keys for
deletion. Expect ~10–20 min.

> If destroy errors on a dependency (leftover ENI/SG from the LB controller, or a
> non-empty bucket), fix the specific resource (Step 1/2) and re-run destroy — it
> is idempotent.

## Step 4 — Secrets cleanup (optional, frees the name immediately)

```bash
aws secretsmanager delete-secret --secret-id "touchstone/validation" \
  --force-delete-without-recovery 2>/dev/null || true
```

## Step 5 — Snapshot cleanup (only if you used Option A in 2a)

```bash
aws rds describe-db-snapshots --snapshot-type manual \
  --query "DBSnapshots[?contains(DBSnapshotIdentifier,'touchstone')].DBSnapshotIdentifier" --output text
aws rds delete-db-snapshot --db-snapshot-identifier touchstone-validation-final 2>/dev/null || true
# ElastiCache final snapshot, if any:
aws elasticache describe-snapshots \
  --query "Snapshots[?contains(SnapshotName,'touchstone')].SnapshotName" --output text
```

## Step 6 — DNS cleanup (Route 53)

Delete the records **you** created (ACM validation CNAME + the `api`,
`robustness`, `app` ALIAS records). If you created a throwaway hosted zone just
for this, delete the zone too (it must be empty of non-default records first):

```bash
ZONE_ID=<your-zone-id>
aws route53 list-resource-record-sets --hosted-zone-id "$ZONE_ID" \
  --query "ResourceRecordSets[?Type=='A' || Type=='CNAME'].Name" --output table
# Delete the touchstone-related records via change-resource-record-sets (DELETE),
# then optionally:
# aws route53 delete-hosted-zone --id "$ZONE_ID"
```

## Step 7 — Terraform state backend cleanup (optional)

Only if you are done with the account entirely (these are tiny/free but tidy):

```bash
aws s3 rm s3://touchstone-tfstate --recursive
aws s3api delete-bucket --bucket touchstone-tfstate
aws dynamodb delete-table --table-name touchstone-tflock
```

## Step 8 — KMS keys (awareness)

The secrets and S3/RDS KMS keys are **scheduled** for deletion (7–30 day window)
by destroy; they cannot be deleted instantly. They cost ~$1/key/month while
pending. Leave them to auto-delete, or check:

```bash
aws kms list-keys --query 'Keys[].KeyId' --output text   # then describe-key to see PendingDeletion
```

---

## Confirm everything was destroyed

Run all of these; each should return **empty / zero / no touchstone resources**.
See `COST_GUARDRAILS.md` "confirm everything was destroyed" for the same list
plus a cost cross-check.

```bash
aws eks list-clusters --query 'clusters' --output text
aws rds describe-db-instances --query "DBInstances[?contains(DBInstanceIdentifier,'touchstone')].DBInstanceIdentifier" --output text
aws elasticache describe-replication-groups --query "ReplicationGroups[?contains(ReplicationGroupId,'touchstone')].ReplicationGroupId" --output text
aws ec2 describe-nat-gateways --filter Name=state,Values=available --query 'NatGateways[].NatGatewayId' --output text
aws ec2 describe-instances --filters Name=instance-state-name,Values=running \
  --query "Reservations[].Instances[?Tags[?Key=='Project' && Value=='touchstone']].InstanceId" --output text
aws elbv2 describe-load-balancers --query "LoadBalancers[?contains(LoadBalancerName,'k8s')].LoadBalancerName" --output text
aws s3 ls | grep touchstone || echo "no touchstone buckets"
aws ec2 describe-addresses --query 'Addresses[].PublicIp' --output text    # leftover EIPs cost money
```

If any line returns a touchstone/k8s resource, delete it manually before you
stop watching the bill. The usual stragglers are: an **orphaned ALB**, leftover
**EIPs** (from NAT), a **final RDS snapshot**, and **PendingDeletion KMS keys**
(harmless, auto-delete).

Finally, check the **Billing console → Cost Explorer** the next day to confirm
spend flatlines.
