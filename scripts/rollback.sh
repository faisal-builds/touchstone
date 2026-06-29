#!/usr/bin/env bash
# Helm rollback helper for the Touchstone release.
#
# SAFE BY DEFAULT: with no flags this only PLANS the rollback (helm history +
# `helm rollback --dry-run`). It performs a real rollback only when you pass
# --execute, and only against whatever kube-context your kubeconfig already
# points at. It never configures cloud credentials and never touches AWS.
#
# Usage:
#   scripts/rollback.sh [--release R] [--namespace N] [--revision REV] [--execute]
#
#   --revision REV   target revision (default: the previous successful revision)
#   --execute        actually run the rollback (default: dry-run plan only)
set -euo pipefail

RELEASE="touchstone"
NAMESPACE="touchstone"
REVISION=""
EXECUTE=0

while [ $# -gt 0 ]; do
  case "$1" in
    --release)   RELEASE="$2"; shift 2 ;;
    --namespace) NAMESPACE="$2"; shift 2 ;;
    --revision)  REVISION="$2"; shift 2 ;;
    --execute)   EXECUTE=1; shift ;;
    -h|--help)   grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

if ! command -v helm >/dev/null 2>&1; then
  echo "helm is required but not installed." >&2; exit 1
fi

echo "Release:   $RELEASE"
echo "Namespace: $NAMESPACE"
echo "Context:   $(kubectl config current-context 2>/dev/null || echo '<none — kubeconfig not set>')"
echo

echo "== helm history =="
helm history "$RELEASE" -n "$NAMESPACE" || {
  echo "Could not read release history (is the release deployed / kubeconfig set?)." >&2
  exit 1
}

# Default target: the previous revision (current - 1).
if [ -z "$REVISION" ]; then
  CURRENT=$(helm history "$RELEASE" -n "$NAMESPACE" -o json | grep -o '"revision":[0-9]*' | tail -n1 | grep -o '[0-9]*')
  if [ -z "${CURRENT:-}" ] || [ "$CURRENT" -le 1 ]; then
    echo "No previous revision to roll back to." >&2; exit 1
  fi
  REVISION=$((CURRENT - 1))
fi
echo
echo "Target revision: $REVISION"

if [ "$EXECUTE" -eq 0 ]; then
  echo
  echo "== DRY RUN (no changes applied) =="
  helm rollback "$RELEASE" "$REVISION" -n "$NAMESPACE" --dry-run
  echo
  echo "Re-run with --execute to perform the rollback above."
  exit 0
fi

echo
echo "== EXECUTING ROLLBACK =="
helm rollback "$RELEASE" "$REVISION" -n "$NAMESPACE" --wait --timeout 10m
kubectl -n "$NAMESPACE" rollout status deploy/"$RELEASE"-control-plane --timeout=5m
echo "✓ rolled back $RELEASE to revision $REVISION"
