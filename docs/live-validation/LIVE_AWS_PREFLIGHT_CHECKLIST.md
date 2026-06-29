# Live AWS Validation — Pre-flight Checklist

Complete **every** item here before running `FIRST_DEPLOY_RUNBOOK.md`. This is
written for a first-time deploy into a **throwaway** AWS account that you will
fully destroy afterwards (`TEARDOWN_RUNBOOK.md`). Read `COST_GUARDRAILS.md`
alongside this — the stock Terraform defaults are production-sized and will cost
~$45–55/day if you do not apply the lean overrides below.

> Scope note this validation can and cannot cover:
> - **gVisor (runsc)** isolation is validatable on standard EKS managed nodes.
> - **Firecracker** is **not** deployable on stock EKS managed node groups (it
>   needs bare-metal instances + Bottlerocket/Kata). Treat Firecracker as
>   out-of-scope for this run unless you stand up a bare-metal pool; the
>   verification engine's backend abstraction is identical either way.
> - **Kafka/MSK is NOT provisioned by the Terraform** in this repo. You must
>   supply a broker. For validation we use **Redpanda in-cluster** (cheap, fast);
>   MSK is the production path. See step 9.

---

## 1. AWS account requirements

- [ ] A **dedicated, empty AWS account** (ideally a throwaway member account in
      an Organization, or a brand-new standalone account). Never validate in an
      account that holds anything you care about.
- [ ] Root email access (for closing the account later if you choose to).
- [ ] An IAM user or SSO role for yourself with admin-equivalent access (see §2).
      Do **not** use the root user for deploys.
- [ ] Service quotas sufficient for the stack (new accounts are usually fine):
  - [ ] **Elastic IPs**: ≥ 2 (NAT gateways consume one per AZ).
  - [ ] **vCPUs (On-Demand Standard, e.g. m6i/t3)**: ≥ 32 for the default sizing,
        ≥ 16 for the lean sizing. Check **Service Quotas → EC2 → Running On-Demand
        Standard instances**; new accounts sometimes start at a low limit and a
        quota increase can take hours — request early if needed.
  - [ ] No SCP/Organization guardrail blocking EKS/RDS/ElastiCache/NAT.
- [ ] Billing is set up and a **payment method is attached** (so resources don't
      fail to create), and you accept that this account will incur charges.

## 2. IAM permissions required

The principal that runs Terraform creates infrastructure across many services.
For a throwaway validation account the pragmatic choice is the AWS-managed
**`AdministratorAccess`** policy on your deploy user/role. If you must scope it,
the deploy principal needs create/describe/delete on:

- [ ] **EC2 / VPC** (VPC, subnets, route tables, NAT gateways, EIPs, security
      groups, ENIs)
- [ ] **EKS** (clusters, node groups, addons, OIDC provider)
- [ ] **IAM** (roles, policies, instance profiles, OIDC provider, `iam:PassRole`)
- [ ] **RDS** (instances, subnet groups, parameter groups, snapshots)
- [ ] **ElastiCache** (replication groups, subnet groups)
- [ ] **S3** (buckets, objects, bucket policies, lifecycle, public-access-block)
- [ ] **KMS** (keys, aliases, grants)
- [ ] **Secrets Manager** (secrets, versions)
- [ ] **ACM** (request/describe/delete certificates)
- [ ] **Elastic Load Balancing** (created later by the AWS Load Balancer
      Controller from the Ingress)
- [ ] **DynamoDB** + **S3** for the Terraform remote-state lock/bucket (§6)

Two **IRSA** roles are created by the Terraform itself (not by you) and used
in-cluster — you do not need to pre-create them:
- `*-app` — S3 `GetObject/PutObject/DeleteObject/ListBucket` on the artifact
  bucket (used by the verification engine and RHD worker).
- `*-external-secrets` — `secretsmanager:GetSecretValue/DescribeSecret` (used by
  the External Secrets Operator).

## 3. Region choice

- [ ] Default and recommended: **`us-east-1`**. The Terraform `region` defaults to
      it, the remote-state backend in `versions.tf` is pinned to it, and it has
      the widest instance/quota availability and lowest prices.
- [ ] If you change the region, you must change it in **three** places:
  `terraform/versions.tf` (the `backend "s3"` block), `terraform.tfvars`
  (`region`), and any `--region` flags in the runbooks. Keep it `us-east-1` for
  your first run to avoid mismatches.
- [ ] Confirm EKS `1.30` (the chart's `cluster_version`) is offered in your
      region (it is in `us-east-1`).

## 4. Domain / DNS requirements

The chart serves three hostnames behind one ALB, and Terraform requests a
DNS-validated ACM certificate:

| Hostname | Backend |
|---|---|
| `api.<domain>` | control-plane |
| `robustness.<domain>` | reward-hacking-detector |
| `app.<domain>` | web dashboard |

- [ ] You control a domain and can edit its DNS, **or** (recommended for a
      throwaway) you register/transfer a cheap domain into **Route 53** so DNS is
      in-account and ACM validation + ALB alias records are one step.
- [ ] A **Route 53 public hosted zone** for the domain exists (or will, in step 5
      of the runbook). Note its **Zone ID**.
- [ ] You will create: (a) the **ACM DNS-validation** CNAME records, then (b)
      **A/ALIAS** records for `api`, `robustness`, `app` → the ALB. Both are in
      the runbook.
- [ ] Pick a throwaway subdomain pattern if you like, e.g.
      `*.validation.<yourdomain>`, and set `domain_name = "validation.<yourdomain>"`.

> If you genuinely have no domain, you can still validate the API/SDK/event/
> sandbox paths via `kubectl port-forward` (the runbook shows this), and skip the
> ALB/TLS/dashboard-over-HTTPS checks. A domain is only required for the public
> ingress + dashboard-in-browser checks.

## 5. Required secrets

You do **not** hand-write app secrets. Terraform generates them and writes a
single Secrets Manager bundle `touchstone/<environment>` containing:

- `TOUCHSTONE_JWT_SECRET`, `TOUCHSTONE_RHD_JWT_SECRET` (generated, shared)
- `TOUCHSTONE_DATABASE_URL`, `TOUCHSTONE_VERIFY_DATABASE_URL`,
  `TOUCHSTONE_RISK_DATABASE_URL`, `TOUCHSTONE_AUDIT_DATABASE_URL`,
  `TOUCHSTONE_RHD_DATABASE_URL` (all the RDS URL with generated master password)
- `TOUCHSTONE_REDIS_URL`

The External Secrets Operator syncs this bundle into the
`touchstone-secrets` Kubernetes Secret at runtime.

Secrets **you** must provide out-of-band:
- [ ] **Container registry pull access** for the cluster. The chart defaults to
      `ghcr.io/touchstone`; for a throwaway, pushing the images to this account's
      **ECR** and pulling via the node role is simplest (see §8 and the runbook).
- [ ] (Optional) **`ANTHROPIC_API_KEY`** — only if you want to validate *real*
      model-as-judge grading. The mock provider is used by default; you can skip
      this for V1 validation. If used, add it to the Secrets Manager bundle and
      reference it from the chart `config`.

## 6. Terraform remote state (one-time bootstrap)

`versions.tf` configures an S3 backend with a DynamoDB lock. These must exist
**before** `terraform init`:

- [ ] S3 bucket **`touchstone-tfstate`** (versioned) in `us-east-1`.
- [ ] DynamoDB table **`touchstone-tflock`** with primary key `LockID` (String).

(The runbook step 0 creates both with copy-paste commands. Bucket names are
global — if `touchstone-tfstate` is taken, pick a unique name and update the
`backend "s3"` block.)

## 7. Required environment variables (your shell)

Set these locally before starting; the runbook assumes them:

```bash
export AWS_PROFILE=touchstone-validation      # an admin profile for the throwaway account
export AWS_REGION=us-east-1
export TF_VAR_environment=validation          # NOT "production" — keeps names/secret key throwaway-scoped
export TF_VAR_domain_name=validation.yourdomain.com
export CLUSTER_NS=touchstone
```

- [ ] `aws sts get-caller-identity` returns the **throwaway** account ID (double-check!).

## 8. Local machine requirements & tools to install

| Tool | Min version | Check |
|---|---|---|
| AWS CLI v2 | 2.x | `aws --version` |
| Terraform | ≥ 1.6 | `terraform version` |
| kubectl | ≥ 1.27 | `kubectl version --client` |
| Helm | ≥ 3.14 | `helm version` |
| Docker / buildx | recent | `docker version` (only if you build/push images) |
| jq | any | `jq --version` |
| Python | 3.12 | `python --version` (for the SDK smoke / load test) |
| Node.js | ≥ 20 | `node --version` (only for the TS SDK smoke) |
| git | any | to clone this repo |

- [ ] `eksctl` (optional, convenient for add-ons): `eksctl version`.
- [ ] Cloned repo and you are in its root for all relative paths
      (`deploy/...`, `load-tests/...`).
- [ ] You have **images to deploy**. Either:
  - [ ] the release pipeline already pushed `ghcr.io/<org>/*:<tag>` and your
        cluster can pull them; **or**
  - [ ] you will build and push the seven images + the sandbox image to this
        account's ECR (runbook step 2b) and point `image.registry` at it.

## 9. Kafka/broker decision (required — there is no MSK in Terraform)

- [ ] Choose **Redpanda in-cluster** for validation (recommended): one Helm
      install, no extra AWS cost beyond node capacity, Kafka-API compatible. The
      runbook installs it and sets `externalServices.kafkaBrokers` to its
      in-cluster Service. **or**
- [ ] Stand up **MSK** separately (production-representative, ~$15/day for 3
      brokers, ~30 min to provision) and use its bootstrap brokers. Not
      recommended for a throwaway.

## 10. Estimated temporary AWS cost (see COST_GUARDRAILS.md for the breakdown)

| Sizing | ~per hour | ~per day | ~per week |
|---|---|---|---|
| **Stock defaults** (db.r6g.large multi-AZ, cache.r6g.large×2, 3× m6i.large + 2× m6i.xlarge, 3 NAT) | ~$1.90–2.30 | ~$45–55 | ~$320–380 |
| **Lean validation** (overrides in COST_GUARDRAILS §lean) | ~$0.55–0.75 | ~$13–18 | ~$95–125 |

These are **approximate** us-east-1 on-demand figures — confirm with the AWS
Pricing Calculator. The single biggest lever is **not leaving it running**: a
half-day validation on the lean config is ~$7–9.

## 11. Safety checks to avoid unexpected bills

Do these **before** `terraform apply`:

- [ ] Create an **AWS Budget** with an alert at $20/day or your comfort level
      (COST_GUARDRAILS §budgets has copy-paste CLI).
- [ ] Enable **Cost Anomaly Detection** (free) on the account.
- [ ] Enable **billing alerts** (CloudWatch billing metric / a $50 alarm).
- [ ] Decide your **time box** now (e.g. "destroy within 8 hours") and set a
      literal calendar reminder.
- [ ] Apply the **lean sizing** overrides unless you specifically need
      production-representative numbers.
- [ ] Know the **teardown gotchas** in advance (they will block `destroy` if you
      don't): RDS has `deletion_protection=true` and `skip_final_snapshot=false`;
      the S3 artifact bucket is **versioned** with no `force_destroy`; Secrets
      Manager deletes with a recovery window. `TEARDOWN_RUNBOOK.md` handles all
      three — read it before you apply, not after.
- [ ] Confirm you can run `TEARDOWN_RUNBOOK.md` end to end and that
      `COST_GUARDRAILS.md` "confirm everything was destroyed" passes.

---

When every box is checked, proceed to `FIRST_DEPLOY_RUNBOOK.md`.
