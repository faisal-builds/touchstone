# First Deploy Runbook — Touchstone V1 on AWS/EKS

Step-by-step, copy-paste deploy into a throwaway account. Assumes you finished
`LIVE_AWS_PREFLIGHT_CHECKLIST.md` and exported its environment variables. Run
everything from the **repo root** unless a step says otherwise.

> Time budget: ~45–70 min, dominated by EKS (~12–15 min) and RDS (~10–15 min)
> creation. Keep `TEARDOWN_RUNBOOK.md` open in another tab.

Sanity gate (run first, every time):

```bash
aws sts get-caller-identity --query Account --output text   # MUST be the throwaway account
echo "$AWS_REGION $TF_VAR_environment $TF_VAR_domain_name"   # us-east-1 validation validation.yourdomain.com
```

---

## Step 0 — Bootstrap Terraform remote state (one-time per account)

`versions.tf` uses an S3 backend + DynamoDB lock that must exist first.

```bash
aws s3api create-bucket --bucket touchstone-tfstate --region us-east-1
aws s3api put-bucket-versioning --bucket touchstone-tfstate \
  --versioning-configuration Status=Enabled
aws dynamodb create-table --table-name touchstone-tflock \
  --attribute-definitions AttributeName=LockID,AttributeType=S \
  --key-schema AttributeName=LockID,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST --region us-east-1
```

> If `touchstone-tfstate` is globally taken, choose a unique name and update the
> `bucket` in `deploy/terraform/versions.tf`.

## Step 1 — Provision infrastructure (Terraform)

```bash
cd deploy/terraform
cp terraform.tfvars.example validation.tfvars
```

Edit `validation.tfvars`: set `environment = "validation"`, `domain_name =
"validation.yourdomain.com"`, and **apply the lean sizing** (cheaper RDS/Redis +
2 AZs) from `COST_GUARDRAILS.md` §lean unless you need production-representative
numbers. The node instance types and RDS HA flags are hardcoded in the modules;
`COST_GUARDRAILS.md` §lean lists the exact one-line module edits (and a reminder
to `git checkout` them afterward).

```bash
terraform init      # connects to the S3 backend from Step 0
terraform plan  -var-file=validation.tfvars -out tfplan
terraform apply tfplan
```

Capture outputs (you'll wire these into Helm):

```bash
terraform output
export RDS_HOST=$(terraform output -raw rds_endpoint)
export REDIS_HOST=$(terraform output -raw elasticache_endpoint)
export ARTIFACT_BUCKET=$(terraform output -raw artifact_bucket)
export APP_ROLE_ARN=$(terraform output -raw irsa_app_role_arn)
export ESO_ROLE_ARN=$(terraform output -raw irsa_external_secrets_role_arn)
export ACM_ARN=$(terraform output -raw acm_certificate_arn)
export SECRET_KEY=$(terraform output -raw secrets_manager_key)
export CLUSTER_NAME=$(terraform output -raw cluster_name)
cd ../..
```

## Step 1b — Complete ACM certificate validation (DNS)

The ACM cert is `DNS`-validated. Create the validation record(s) in your hosted
zone. If your domain is in **Route 53 in this account**, the easiest path:

```bash
CERT_ARN="$ACM_ARN"
aws acm describe-certificate --certificate-arn "$CERT_ARN" \
  --query 'Certificate.DomainValidationOptions[].ResourceRecord' --output table
# Create the CNAME(s) shown above in your hosted zone, then wait:
aws acm wait certificate-validated --certificate-arn "$CERT_ARN"
echo "ACM validated"
```

> The cert covers `<domain>` and `*.<domain>` so one wildcard validation covers
> `api`, `robustness`, and `app`.

## Step 2 — Connect kubectl to the cluster

```bash
aws eks update-kubeconfig --name "$CLUSTER_NAME" --region "$AWS_REGION"
kubectl get nodes -L touchstone.io/sandbox     # expect general + sandbox-gvisor nodes Ready
```

### Step 2b — (Optional) Push images to ECR for this account

Skip if your cluster can already pull `ghcr.io/<org>/*:<tag>`. Otherwise:

```bash
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
ECR="$ACCOUNT.dkr.ecr.$AWS_REGION.amazonaws.com/touchstone"
aws ecr get-login-password --region "$AWS_REGION" | \
  docker login --username AWS --password-stdin "$ACCOUNT.dkr.ecr.$AWS_REGION.amazonaws.com"
for svc in control-plane verification-engine risk-engine audit-engine \
           reward-hacking-detector web sandbox; do
  aws ecr create-repository --repository-name "touchstone/$svc" --region "$AWS_REGION" 2>/dev/null || true
  docker build -t "$ECR/$svc:1.0.0" -f deploy/docker/$svc.Dockerfile .   # adjust to your Dockerfiles
  docker push "$ECR/$svc:1.0.0"
done
export IMAGE_REGISTRY="$ECR"
```

(If you use the repo's release pipeline instead, point `image.registry` at GHCR
and ensure an imagePullSecret or public visibility.)

## Step 3 — Install cluster add-ons (once per cluster)

These operators are prerequisites the chart assumes. Install all four.

**a) AWS Load Balancer Controller** (realizes the ALB Ingress) — follow the
official Helm install, providing `--set clusterName=$CLUSTER_NAME` and an IRSA
role with the AWS LB Controller policy. Verify:

```bash
kubectl -n kube-system get deploy aws-load-balancer-controller
```

**b) External Secrets Operator** + a `ClusterSecretStore` named
`aws-secrets-manager` using the ESO IRSA role:

```bash
helm repo add external-secrets https://charts.external-secrets.io && helm repo update
helm install external-secrets external-secrets/external-secrets \
  -n external-secrets --create-namespace --wait

cat <<EOF | kubectl apply -f -
apiVersion: external-secrets.io/v1beta1
kind: ClusterSecretStore
metadata:
  name: aws-secrets-manager
spec:
  provider:
    aws:
      service: SecretsManager
      region: ${AWS_REGION}
      auth:
        jwt:
          serviceAccountRef:
            name: external-secrets
            namespace: external-secrets
EOF
```

(Annotate the `external-secrets` ServiceAccount with
`eks.amazonaws.com/role-arn: $ESO_ROLE_ARN` so it can read the secret.)

**c) Prometheus Operator CRDs** (the chart ships `ServiceMonitor`s):

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm install kube-prometheus-stack prometheus-community/kube-prometheus-stack \
  -n monitoring --create-namespace --wait
kubectl apply -f deploy/observability/   # PrometheusRules / dashboards
```

**d) gVisor (runsc) on the sandbox node pool.** Install the
`containerd-shim-runsc-v1` handler on nodes labeled `touchstone.io/sandbox=gvisor`
(a DaemonSet installer that drops the runsc binary + shim and patches containerd
config), then apply the RuntimeClass:

```bash
# Install runsc via your preferred DaemonSet installer onto the sandbox pool
# (nodeSelector touchstone.io/sandbox=gvisor, toleration for that taint), then:
kubectl apply -f deploy/k8s/30-runtimeclass-gvisor.yaml
kubectl get runtimeclass gvisor       # handler: runsc
```

**e) metrics-server** (for HPAs), if not already present:

```bash
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml
```

## Step 4 — Namespace scaffolding

```bash
kubectl apply -f deploy/k8s/    # namespace, quotas, priorityclasses, runtimeclass, baseline netpol
kubectl get ns touchstone
```

## Step 5 — Broker (Redpanda in-cluster, for validation)

Terraform does not provision Kafka. Install Redpanda and note its in-cluster
bootstrap address:

```bash
helm repo add redpanda https://charts.redpanda.com && helm repo update
helm install redpanda redpanda/redpanda -n redpanda --create-namespace \
  --set statefulset.replicas=1 --set resources.cpu.cores=1 --wait
# In-cluster Kafka API endpoint (adjust to the chart's Service name):
export KAFKA_BROKERS="redpanda.redpanda.svc.cluster.local:9093"
```

> Production uses MSK; set `externalServices.kafkaBrokers` to its bootstrap
> brokers instead and skip this step.

## Step 6 — Wire Terraform outputs into the Helm overlay

Edit `deploy/helm/touchstone/values-production.yaml` and replace the markers
(use the env vars captured in Step 1):

| Helm value | Source |
|---|---|
| `image.registry` | `$IMAGE_REGISTRY` (or your GHCR org) |
| `externalServices.postgresHost` | `$RDS_HOST` |
| `externalServices.redisHost` | `$REDIS_HOST` |
| `externalServices.kafkaBrokers` | `$KAFKA_BROKERS` |
| `externalServices.artifactStoreUri` | `s3://$ARTIFACT_BUCKET` |
| `serviceAccount.annotations.eks.amazonaws.com/role-arn` | `$APP_ROLE_ARN` |
| `ingress.tls.certificateArn` | `$ACM_ARN` |
| `secrets.externalSecretRemoteKey` | `$SECRET_KEY` (e.g. `touchstone/validation`) |
| `config.corsOrigins` | `https://app.<domain>` |
| `config.sandboxImage` | `$IMAGE_REGISTRY/sandbox:1.0.0` |

Confirm the synced secret appears before deploying the apps:

```bash
kubectl -n touchstone get externalsecret,secret | grep touchstone-secrets
```

## Step 7 — Deploy the platform (Helm)

```bash
helm upgrade --install touchstone deploy/helm/touchstone \
  -n touchstone -f deploy/helm/touchstone/values-production.yaml \
  --wait --timeout 12m --atomic
```

`--atomic` auto-rolls-back a failed install so you never sit in a half-applied
state.

## Step 8 — Database migrations (three schema owners)

Run once, after the pods are up (they share the same RDS but own separate
schemas with separate Alembic histories). Migrations run **inside** the pods,
which already have the DB URLs from the synced secret:

```bash
kubectl -n touchstone exec deploy/touchstone-control-plane -- alembic upgrade head
kubectl -n touchstone exec deploy/touchstone-reward-hacking-detector -- alembic upgrade head
kubectl -n touchstone exec deploy/touchstone-audit-engine -- alembic upgrade head
```

Then restart the consumers so they pick up the schema cleanly:

```bash
kubectl -n touchstone rollout restart deploy/touchstone-verification-engine \
  deploy/touchstone-risk-engine deploy/touchstone-audit-engine \
  deploy/touchstone-reward-hacking-detector-worker \
  deploy/touchstone-control-plane-robustness-consumer
```

## Step 9 — DNS / TLS (point hostnames at the ALB)

After Step 7 the AWS LB Controller creates an ALB for the Ingress. Get its
DNS name and create A/ALIAS records for the three hostnames:

```bash
kubectl -n touchstone get ingress
ALB=$(kubectl -n touchstone get ingress -o jsonpath='{.items[0].status.loadBalancer.ingress[0].hostname}')
echo "ALB: $ALB"
# In Route 53, create ALIAS (or CNAME) records:
#   api.<domain>         -> $ALB
#   robustness.<domain>  -> $ALB
#   app.<domain>         -> $ALB
```

TLS is terminated at the ALB using the ACM cert from Step 1b — no per-pod certs.

## Step 10 — Verify

**Pods** — all Running/Ready, sandbox workers on the gVisor pool:

```bash
kubectl -n touchstone get pods -o wide
kubectl -n touchstone get pods -l touchstone.io/pool=sandbox -o wide   # on sandbox-gvisor nodes
```

**Services** — eight workloads (control-plane, verification-engine, risk-engine,
audit-engine, reward-hacking-detector, reward-hacking-detector-worker,
control-plane-robustness-consumer, web):

```bash
kubectl -n touchstone get deploy
kubectl -n touchstone rollout status deploy/touchstone-control-plane
```

**Readiness via port-forward** (works even without DNS):

```bash
kubectl -n touchstone port-forward svc/touchstone-control-plane 8000:8000 &
curl -fsS localhost:8000/readyz | jq        # expect db + redis checks healthy
curl -fsS localhost:8000/healthz | jq
kill %1
```

**Ingress / TLS** (needs Step 9 DNS to have propagated):

```bash
curl -fsS https://api.<domain>/healthz | jq
curl -fsSI https://app.<domain>/            # 200 + valid TLS chain
```

**Dashboard** — browse `https://app.<domain>`; it should load and talk to
`api.<domain>`.

When all of Step 10 passes, proceed to `LIVE_VALIDATION_TEST_PLAN.md`. When you
are done, run `TEARDOWN_RUNBOOK.md` **the same day**.

---

## If something fails

- Pods `CrashLoopBackOff` right after install → almost always missing migrations
  (Step 8) or the secret not synced (Step 6). Check
  `kubectl -n touchstone logs deploy/touchstone-control-plane`.
- `ImagePullBackOff` → `image.registry`/pull access (Step 2b).
- Ingress has no ADDRESS → AWS LB Controller not installed/healthy (Step 3a) or
  subnets not tagged for ELB discovery.
- Sandbox workers `Pending` → gVisor RuntimeClass/nodes not ready (Step 3d), or
  the taint/toleration/nodeSelector mismatch.
- `--atomic` rolled the release back → fix the root cause and re-run Step 7; you
  are never left half-deployed.
