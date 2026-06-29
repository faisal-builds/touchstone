#!/usr/bin/env bash
# Run the Touchstone load suite with a named profile.
#
#   ./run.sh [profile] [extra locust args...]
#
# Profiles: smoke | local | staging | stress  (default: smoke)
# The profile's user count, spawn rate, and duration come from
# touchstone_load/config.py — the single source of truth — so they never drift
# from the thresholds enforced at the end of the run.
#
# Targets are set via environment variables:
#   TOUCHSTONE_LOAD_HOST       control-plane base URL (default http://localhost:8000)
#   TOUCHSTONE_LOAD_RHD_URL    reward-hacking-detector base URL (default :8030)
#   TOUCHSTONE_LOAD_ENABLE_RHD set to "true" to include RHD scenarios
#   TOUCHSTONE_LOAD_ARTIFACT_REF  artifact ref submitted for verification
set -euo pipefail

PROFILE="${1:-smoke}"
shift || true
export TOUCHSTONE_LOAD_PROFILE="$PROFILE"

HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"
export PYTHONPATH="$HERE:${PYTHONPATH:-}"

HOST="${TOUCHSTONE_LOAD_HOST:-http://localhost:8000}"

# Pull the scaling knobs for this profile from the single source of truth.
read -r USERS SPAWN RUN_TIME <<EOF
$(python -c "from touchstone_load.config import get_profile as g; p=g(); print(p.users, p.spawn_rate, p.run_time)")
EOF

echo "[run.sh] profile=$PROFILE users=$USERS spawn=$SPAWN run_time=$RUN_TIME host=$HOST"

exec locust -f locustfile.py --headless \
    -u "$USERS" -r "$SPAWN" -t "$RUN_TIME" \
    --host "$HOST" \
    "$@"
