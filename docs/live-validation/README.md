# Live AWS Validation Package

Everything needed to validate Touchstone V1 in a **throwaway** AWS/Kubernetes
environment and tear it down cleanly, cost-controlled. Read and execute in this
order:

1. **[LIVE_AWS_PREFLIGHT_CHECKLIST.md](LIVE_AWS_PREFLIGHT_CHECKLIST.md)** — account,
   IAM, region, domain, secrets, tools, cost estimate, and the bill-safety setup
   to do **before** anything is created.
2. **[FIRST_DEPLOY_RUNBOOK.md](FIRST_DEPLOY_RUNBOOK.md)** — copy-paste Terraform →
   add-ons → broker → Helm → migrations → DNS/TLS → verification.
3. **[LIVE_VALIDATION_TEST_PLAN.md](LIVE_VALIDATION_TEST_PLAN.md)** — API/SDK
   smoke, dashboard e2e, Kafka event-flow, gVisor sandbox, load/perf, DR drill,
   each with pass/fail criteria.
4. **[TEARDOWN_RUNBOOK.md](TEARDOWN_RUNBOOK.md)** — destroy everything safely,
   including the three blockers (RDS protection/snapshot, versioned S3, Secrets
   recovery window) and the orphaned-resource sweep.
5. **[COST_GUARDRAILS.md](COST_GUARDRAILS.md)** — daily/weekly cost, the lean
   override config, budgets/alerts, and the "confirm destroyed" checklist.

## Three things to know up front

- **Use a dedicated throwaway account** and **time-box** the run (destroy the same
  day). Lean config ≈ $13–18/day; stock defaults ≈ $45–55/day.
- **Terraform does not provision Kafka.** Use in-cluster **Redpanda** for
  validation (the runbook installs it); MSK is the production path.
- **Firecracker is out of scope** on stock EKS managed nodes; **gVisor (runsc)**
  isolation is what gets validated. The engine's sandbox abstraction is identical
  either way.

This package is operational runbooks only — it adds no product code and changes
no service behavior. It complements the existing
[`../deployment-guide.md`](../deployment-guide.md),
[`../operations-guide.md`](../operations-guide.md), and
[`../disaster-recovery.md`](../disaster-recovery.md).
