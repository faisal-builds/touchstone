#!/usr/bin/env bash
# Infrastructure preflight — OFFLINE VALIDATION ONLY.
#
# Runs the structural validators for the deploy layer that need no cloud account:
# docker-compose config, terraform fmt+validate, helm lint, and Kubernetes
# manifest validation. Passing here means the manifests are *well-formed*, NOT
# that the infrastructure is provisioned or deploy-ready (see deploy/*/README,
# labelled "DESIGN — not yet provisioned").
#
# This script NEVER contacts AWS/Kubernetes: no terraform apply, no helm install,
# no kubectl against a live cluster. Tools that are absent are reported as
# SKIPPED (so CI, where they are installed, validates for real).
set -uo pipefail
cd "$(dirname "$0")/.."

pass=0; fail=0; skip=0
ok()   { printf "  \033[32m✓ %s\033[0m\n" "$1"; pass=$((pass+1)); }
bad()  { printf "  \033[31m✗ %s\033[0m\n" "$1"; fail=$((fail+1)); }
note() { printf "  \033[33m• %s (SKIPPED)\033[0m\n" "$1"; skip=$((skip+1)); }
have() { command -v "$1" >/dev/null 2>&1; }

echo "== docker compose =="
if have docker; then
  if docker compose config --quiet 2>/dev/null; then ok "docker compose config"; else bad "docker compose config"; fi
else
  note "docker not installed"
fi

echo "== terraform (fmt + validate, no backend) =="
if have terraform; then
  if terraform -chdir=deploy/terraform fmt -check -recursive >/dev/null 2>&1; then
    ok "terraform fmt"
  else
    bad "terraform fmt (run: terraform -chdir=deploy/terraform fmt -recursive)"
  fi
  if terraform -chdir=deploy/terraform init -backend=false -input=false >/dev/null 2>&1 \
     && terraform -chdir=deploy/terraform validate >/dev/null 2>&1; then
    ok "terraform validate"
  else
    bad "terraform validate"
  fi
else
  note "terraform not installed"
fi

echo "== helm lint =="
if have helm; then
  if helm lint deploy/helm/touchstone -f deploy/helm/touchstone/values-production.yaml >/dev/null 2>&1; then
    ok "helm lint"
  else
    bad "helm lint"
  fi
else
  note "helm not installed"
fi

echo "== kubernetes manifests =="
if have kubeconform; then
  # Offline schema validation — the authoritative check (mirrors CI).
  if kubeconform -strict -ignore-missing-schemas -summary deploy/k8s/ >/dev/null 2>&1; then
    ok "kubeconform (raw manifests)"
  else
    bad "kubeconform (raw manifests)"
  fi
elif have kubectl && kubectl config current-context >/dev/null 2>&1; then
  # Fallback: client-side dry-run. Needs a kube-context (it fetches OpenAPI),
  # so it is only attempted when one is configured — never contacts a cluster
  # for changes.
  if kubectl apply --dry-run=client -f deploy/k8s/ >/dev/null 2>&1; then
    ok "kubectl --dry-run=client"
  else
    bad "kubectl --dry-run=client"
  fi
else
  note "kubeconform not installed (kubectl dry-run needs a kube-context); CI runs kubeconform"
fi

echo
echo "preflight: $pass passed, $fail failed, $skip skipped"
echo "NOTE: validation only — 'well-formed', not 'deploy-ready'."
[ "$fail" -eq 0 ]
