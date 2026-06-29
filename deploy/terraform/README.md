# Touchstone AWS Infrastructure (Terraform)

Provisions the production AWS footprint for Touchstone:

| Module | Resources |
|--------|-----------|
| `modules/vpc` | VPC, 3× public / private / database subnets across AZs, IGW, per-AZ NAT gateways, route tables |
| `modules/eks` | EKS control plane, OIDC provider (IRSA), `general` + `sandbox-gvisor` managed node groups |
| `modules/rds` | Multi-AZ encrypted PostgreSQL 16, parameter group (`force_ssl`), SG, KMS, automated backups |
| `modules/elasticache` | Multi-AZ Redis 7 replication group, at-rest + in-transit encryption, auth token |
| `modules/s3` | Versioned, KMS-encrypted artifact bucket, TLS-only policy, lifecycle rules |
| `modules/iam` | IRSA roles for the app (S3 access) and the External Secrets Operator (Secrets Manager) |

Root `main.tf` also creates the ACM certificate, the KMS key for secrets, and the
Secrets Manager bundle (`touchstone/<env>`) that the External Secrets Operator
syncs into the cluster.

## Usage

```bash
cd deploy/terraform
terraform init
terraform plan  -var-file=production.tfvars   # copy from terraform.tfvars.example
terraform apply -var-file=production.tfvars
```

## Wiring outputs into Helm

```bash
terraform output -raw rds_endpoint            # -> externalServices.postgresHost
terraform output -raw elasticache_endpoint    # -> externalServices.redisHost
terraform output -raw artifact_bucket         # -> externalServices.artifactStoreUri (s3://)
terraform output -raw irsa_app_role_arn       # -> serviceAccount.annotations
terraform output -raw acm_certificate_arn     # -> ingress.tls.certificateArn
terraform output -raw secrets_manager_key     # -> secrets.externalSecretRemoteKey
```

## Notes & honest caveats

- **Validation**: this code was authored in an environment without the
  `terraform` binary or AWS provider plugins, so it was validated by structural
  checks (delimiter/block balance) and careful construction — **not** by a live
  `terraform validate` / `plan`. Run `terraform fmt -check`, `terraform validate`,
  and `tflint`/`checkov` in CI before applying (wired in `.github/workflows`).
- **State backend**: `versions.tf` configures an S3 backend (`touchstone-tfstate`
  + DynamoDB lock table). Create those once via a bootstrap workspace before the
  first `init`.
- **gVisor runtime**: the `sandbox-gvisor` node group is labelled/tainted for
  sandbox pods, but the `runsc` containerd shim must be installed on those nodes
  (launch-template bootstrap or a node installer DaemonSet) — see the operations
  guide.
- **Secret rotation**: `random_password` seeds JWT/DB/Redis credentials on first
  apply. Rotating them is a Secrets Manager + `terraform apply` operation
  documented in the operations guide.
