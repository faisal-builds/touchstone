# Live Validation Test Plan — Touchstone V1

Run after `FIRST_DEPLOY_RUNBOOK.md` Step 10 passes. Each test states **how to
run** and **pass/fail**. Use real hostnames if DNS is up, otherwise
`kubectl port-forward` (noted per test). Record results in the table at the
bottom; the run **passes** only if every Required test passes.

Set up a base URL once:

```bash
export API=https://api.<domain>        # or: kubectl -n touchstone port-forward svc/touchstone-control-plane 8000:8000 & API=http://localhost:8000
export RHD=https://robustness.<domain> # or port-forward svc/touchstone-reward-hacking-detector 8030:8030
```

---

## 1. API smoke tests (Required)

Drive the full tenant + verification path over HTTP. `signup` returns **201**;
`submit` returns **202**.

```bash
SFX=$RANDOM
JWT=$(curl -fsS -X POST $API/v1/auth/signup -H 'content-type: application/json' -d "{
  \"email\":\"val-$SFX@loadtest.io\",\"password\":\"validation-pass-123\",
  \"full_name\":\"Validation\",\"org_name\":\"Val $SFX\",\"org_slug\":\"val-$SFX\"}" | jq -r .access_token)
AUTH="authorization: Bearer $JWT"
WS=$(curl -fsS -X POST $API/v1/workspaces -H "$AUTH" -H 'content-type: application/json' -d "{\"name\":\"ws\",\"slug\":\"ws-$SFX\"}" | jq -r .id)
PROJ=$(curl -fsS -X POST $API/v1/workspaces/$WS/projects -H "$AUTH" -H 'content-type: application/json' -d "{\"name\":\"p\",\"slug\":\"p-$SFX\"}" | jq -r .id)
VER=$(curl -fsS -X POST $API/v1/projects/$PROJ/verifiers -H "$AUTH" -H 'content-type: application/json' -d '{
  "name":"v","slug":"v","verifier_type":"code",
  "definition":{"type":"code","code":"def check(artifact):\n    return {\"score\": 1.0 if artifact == 42 else 0.0}","threshold":1.0}}' | jq -r .id)
# Put an artifact in the bucket the engine reads, then submit:
echo '42' > /tmp/a.json
aws s3 cp /tmp/a.json s3://$ARTIFACT_BUCKET/validation/a.json
RUN=$(curl -fsS -X POST $API/v1/verifications -H "$AUTH" -H 'content-type: application/json' -d "{\"verifier_id\":\"$VER\",\"artifact_ref\":\"validation/a.json\"}" | jq -r .id)
# Poll to completion:
for i in $(seq 1 30); do S=$(curl -fsS $API/v1/verifications/$RUN -H "$AUTH" | jq -r .status); echo $S; [ "$S" = completed -o "$S" = failed ] && break; sleep 2; done
curl -fsS $API/v1/audit -H "$AUTH" | jq 'length'
```

**Pass:** signup 201; workspace/project/verifier created; submit returns a run
id (202); the run reaches `completed`; `/v1/audit` returns ≥ 1 record.
**Fail:** any non-2xx, or the run never leaves `pending`/`running` (→ event flow /
worker problem, see Test 4).

## 2. SDK smoke tests (Required: Python; Optional: TypeScript)

**Python** (`touchstone-sdk`) via the bundled demo, which does
signup → key → workspace → project → verifier → artifact → submit → poll:

```bash
pip install -e sdks/python
TOUCHSTONE_BASE_URL=$API TOUCHSTONE_ARTIFACTS_DIR=./.artifacts python scripts/demo.py
```

**Pass:** the demo prints a completed verification with a score. (If your engine
reads artifacts from S3 only, set the demo to write to the bucket or run it where
its artifact dir is the engine's store; locally-completed status is acceptable
only if a worker processed it.)

**TypeScript** (`@touchstone/sdk`), optional:

```bash
cd sdks/typescript && npm ci && npm run build
node -e "import('@touchstone/sdk').then(async m => { const c = new m.TouchstoneClient({baseUrl: process.env.API}); /* signup+submit per README */ })"
```

**Pass:** client authenticates and submits a verification without error.

## 3. Dashboard e2e checklist (Required if DNS is up)

Browse `https://app.<domain>` and verify:

- [ ] Page loads over valid TLS (no cert warning).
- [ ] Sign up / log in works; you land in an authenticated view.
- [ ] Workspaces/projects/verifiers created via API (Test 1) are visible.
- [ ] Submitting a verification from the UI shows it transition to **completed**.
- [ ] The audit view shows records.
- [ ] No console errors pointing at a wrong/blocked `api.<domain>` origin (CORS).

**Pass:** all boxes checked. **Fail:** TLS error, blank page, CORS failure, or
data not reflecting the backend.

## 4. Redpanda/Kafka event-flow validation (Required)

This proves the asynchronous backbone end-to-end (the thing that cannot be tested
without a live broker + workers).

1. **Verification flow**: the run from Test 1 reaching `completed` proves
   `verification.requested` → verification-engine consumed → executed in the
   sandbox → result persisted.
2. **Risk + audit fan-out**: after a completion, confirm a risk score and audit
   records exist (`/v1/audit` grew; risk-engine logged a `risk.scored`).
3. **Auto-evaluation**: registering a verifier (Test 1) emits
   `verifier.registered`; the RHD auto-evaluates it. Check:
   ```bash
   curl -fsS "$RHD/v1/robustness/verifiers/$VER/evaluations" -H "$AUTH" | jq '.[0].status'
   ```
4. **Single-writer writeback**: when an RHD evaluation completes it emits
   `reward_hacking.robustness_evaluated`; the control-plane consumer writes
   `verifiers.robustness_score`. Confirm the verifier now has a non-null score:
   ```bash
   curl -fsS "$API/v1/projects/$PROJ/verifiers/$VER" -H "$AUTH" | jq '.robustness_score'
   ```
5. **Broker health**: `kubectl -n redpanda exec ... -- rpk cluster info` (or check
   consumer-group lag is bounded, not growing unboundedly).

**Pass:** the verification completes, the RHD evaluation runs, and the verifier
gains a `robustness_score` — i.e. events flow across all services with bounded
consumer lag. **Fail:** runs stick in `pending`, evaluations never appear, or the
score stays null (→ a worker/consumer or broker wiring problem).

## 5. gVisor sandbox validation (Required) / Firecracker (Out of scope)

**Placement** — sandbox workers run under gVisor on the tainted pool:

```bash
kubectl -n touchstone get pod -l touchstone.io/pool=sandbox \
  -o custom-columns=NAME:.metadata.name,RUNTIME:.spec.runtimeClassName,NODE:.spec.nodeName
# RUNTIME must be "gvisor"; NODE must be a sandbox-gvisor node.
```

**Isolation behavior** — register verifiers whose code misbehaves and confirm the
sandbox contains them (submit each like Test 1, observe the run):

- [ ] **CPU/timeout**: `code: "def check(a):\n    while True: pass"` → run ends
      `failed` (timed out/killed), the worker stays healthy, the node is not
      starved.
- [ ] **Network egress blocked**: `code` that opens a socket to an external host →
      blocked/error inside the sandbox, run `failed` with no egress.
- [ ] **Filesystem isolation**: `code` that writes outside its temp dir or reads a
      host path → denied; no effect on the node.

Confirm the runtime is really runsc (not a silent fallback): the chart sets
`config.sandboxAllowFallback: "false"`, so an unavailable runsc should make
sandbox pods fail to schedule rather than run unisolated — verify there was no
fallback in the worker logs.

> **Firecracker** is not validated here: stock EKS managed nodes can't run it. If
> required, stand up a bare-metal/Bottlerocket+Kata pool and repeat the placement
> + isolation checks with that runtimeClass; the engine's backend abstraction is
> identical.

**Pass:** sandbox pods report `runtimeClassName: gvisor` on sandbox nodes, and all
three isolation behaviors hold with no fallback. **Fail:** misbehaving verifiers
affect the node/worker, egress succeeds, or pods ran without runsc.

## 6. Load / performance test execution (Required)

Run the Locust suite against the **live** stack with a worker present, so
completion and throughput gates are enforced:

```bash
pip install -e load-tests
cd load-tests
TOUCHSTONE_LOAD_HOST="$API" \
TOUCHSTONE_LOAD_RHD_URL="$RHD" \
TOUCHSTONE_LOAD_ENABLE_RHD=true \
TOUCHSTONE_LOAD_ARTIFACT_REF="validation/a.json" \
./run.sh staging          # then, optionally: ./run.sh stress
```

**Pass:** `RESULT: PASS` — p95/p99, error rate, verification-poll timeout rate,
and completion p95 all within the `staging` profile thresholds; worker throughput
and queue backlog are bounded (watch the Prometheus consumer-lag metric during
the run). Record the headline numbers (submission RPS, completion p95, worker
throughput) — these are the first production-representative figures.
**Fail:** threshold breach or unbounded backlog under `staging` load.

## 7. Disaster-recovery drill (Required: the fast/cheap subset)

From `docs/disaster-recovery.md`. Do the cheap, fast drills; the full-region
drill is optional and expensive.

- [ ] **RDS Multi-AZ failover** (only if you kept multi-AZ): reboot with failover
      and confirm the platform recovers without data loss:
      ```bash
      aws rds reboot-db-instance --db-instance-identifier <id> --force-failover
      ```
      Re-run Test 1; it should succeed after a brief blip.
- [ ] **Pod resilience**: delete a control-plane and a worker pod; the Deployment
      reschedules and traffic continues (PDBs keep ≥1 available).
      ```bash
      kubectl -n touchstone delete pod -l app=touchstone-control-plane --wait=false
      ```
- [ ] **Audit chain integrity**: after the above, verify the tamper-evident hash
      chain is intact (run the audit-engine's verify path / `/v1/audit` reads
      consistently; the chain should validate end-to-end).
- [ ] **S3 version restore**: delete an artifact object, then restore by removing
      the delete marker (versioning is on) and confirm the engine can read it.
- [ ] **(Optional) PITR restore** to a new instance per the DR doc, validate the
      data, then delete the restored instance (don't leave it running — cost).

**Pass:** the platform recovers from each drill within the documented RTO and the
audit chain validates. **Fail:** data loss beyond RPO, chain breaks, or manual
intervention beyond the runbook is needed.

---

## Results

| # | Test | Required | Result | Notes |
|---|---|---|---|---|
| 1 | API smoke | yes | | |
| 2 | SDK smoke (Python) | yes | | |
| 2 | SDK smoke (TS) | no | | |
| 3 | Dashboard e2e | yes* | | *if DNS up |
| 4 | Event flow (Kafka) | yes | | |
| 5 | gVisor sandbox | yes | | |
| 5 | Firecracker | no | | out of scope |
| 6 | Load/perf | yes | | record numbers |
| 7 | DR drill (fast subset) | yes | | |

**Overall pass:** every Required test passes. On any Required failure, capture
logs (`kubectl -n touchstone logs ...`), file the gap, and either fix-and-retest
or record it as a known issue before teardown. **Tear down the same day** —
`TEARDOWN_RUNBOOK.md`.
