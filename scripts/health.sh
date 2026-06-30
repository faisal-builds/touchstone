#!/usr/bin/env bash
# Poll every HTTP service's health endpoint and print a pass/fail table.
# Exits non-zero if any service is unhealthy. Headless worker services
# (verification/risk/audit engines, RHD worker) have no HTTP port — their health
# is reported from `docker compose ps` instead.
set -uo pipefail

# name|url  (liveness endpoints; readyz where it adds a dependency check)
SERVICES=(
  "control-plane|http://localhost:8000/healthz"
  "control-plane(ready)|http://localhost:8000/readyz"
  "reward-hacking-detector|http://localhost:8030/healthz"
  "ivp|http://localhost:8050/healthz"
  "web|http://localhost:3000/api/health"
)

printf "%-26s %-8s %s\n" "SERVICE" "STATUS" "ENDPOINT"
printf "%-26s %-8s %s\n" "-------" "------" "--------"

fail=0
for entry in "${SERVICES[@]}"; do
  name="${entry%%|*}"
  url="${entry##*|}"
  if curl -fsS -m 3 -o /dev/null "$url" 2>/dev/null; then
    printf "%-26s \033[32m%-8s\033[0m %s\n" "$name" "PASS" "$url"
  else
    printf "%-26s \033[31m%-8s\033[0m %s\n" "$name" "FAIL" "$url"
    fail=1
  fi
done

# Headless workers: report container health/state if the stack is running.
if command -v docker >/dev/null 2>&1; then
  echo
  echo "Headless workers (docker compose state):"
  for svc in verification-engine risk-engine audit-engine reward-hacking-detector-worker; do
    state=$(docker compose ps --format '{{.State}}' "$svc" 2>/dev/null | head -n1)
    [ -z "$state" ] && state="not running"
    printf "  %-32s %s\n" "$svc" "$state"
  done
fi

echo
if [ "$fail" -eq 0 ]; then
  echo "✓ all HTTP services healthy"
else
  echo "✗ one or more services unhealthy (is the stack up? try 'make up')"
fi
exit "$fail"
