# Touchstone Automation

One-command developer and CI automation for the whole monorepo. Everything here
is verifiable **without a live AWS account**: infrastructure is *validated*
(well-formed), never *provisioned*.

## Local developer workflow

Linux/macOS use the `Makefile`; Windows uses the PowerShell mirror `make.ps1`.
Every target exists in both.

| Task | Linux/macOS | Windows |
|------|-------------|---------|
| Install toolchain (venv + editable deps) | `make install` | `./make.ps1 install` |
| Build all images | `make build` | `./make.ps1 build` |
| Start full stack (detached) | `make up` | `./make.ps1 up` |
| Stop stack | `make down` | `./make.ps1 down` |
| Restart stack | `make restart` | `./make.ps1 restart` |
| Rebuild from scratch + recreate | `make rebuild` | `./make.ps1 rebuild` |
| Run all tests (full suite) | `make test` | `./make.ps1 test` |
| Run unit tests (no infra) | `make test-unit` | `./make.ps1 test-unit` |
| Lint (ruff, all packages) | `make lint` | `./make.ps1 lint` |
| Type check (mypy) | `make typecheck` | `./make.ps1 typecheck` |
| Health check (pass/fail table) | `make health` | `./make.ps1 health` |
| Validate docker-compose | `make compose-validate` | `./make.ps1 compose-validate` |
| Offline infra preflight | `make validate-infra` | `./make.ps1 validate-infra` |
| Clean everything | `make clean` | `./make.ps1 clean` |
| **Complete verifiable workflow** | `make all` | `./make.ps1 all` |

`make all` runs **lint + typecheck + unit tests + compose config validation** —
the full set of gates that pass with no infrastructure running. The Docker path
(`build` / `up` / `health`) is separate because it needs the Docker daemon.

### Cross-platform tests

The verifier sandbox uses POSIX `fork`/`rlimits`/`unshare`, which only exist on
Linux (where CI exercises them for real). Sandbox-executing tests **skip
gracefully** on Windows and on CI runners that can't run them via
`sandbox_supported()` — they never fail for environment reasons. Integration
tests that need Postgres skip when the database isn't reachable.

## Docker

- Every service has a multi-stage, non-root Dockerfile.
- HTTP services (control-plane, reward-hacking-detector, ivp, web) carry a
  `HEALTHCHECK`; `docker-compose.yml` adds matching healthchecks and gates
  dependents on `service_healthy`.
- `docker compose config` is validated locally (`make compose-validate`) and in
  CI (the `compose-validate` job).

## GitHub Actions

`.github/workflows/ci.yml` runs on every push/PR:

- Builds + tests every backend service, the Python SDK, the TypeScript SDK, and
  the web dashboard.
- Lint + type checking.
- Uploads JUnit/coverage test artifacts and web/SDK build artifacts.
- Validates docker-compose config.
- Builds every Docker image.

## Safe infrastructure automation (validation only)

These run locally/CI and **never** touch a cloud account. Passing means
"well-formed", not "deploy-ready" — see the `deploy/**` READMEs, labelled
**DESIGN — not yet provisioned**.

- `infra-validation.yml` — `terraform fmt`/`validate`/`tflint`, `helm lint`,
  `helm template`, `kubeconform`, Checkov.
- `scripts/preflight.sh` (`make validate-infra`) — the same validators offline,
  skipping any tool that isn't installed.
- `scripts/rollback.sh` — dry-run by default; a real `helm rollback` only with
  `--execute`, against whatever kube-context the operator already has.
- `scripts/tag-release.sh` — create a semver tag locally; pushing (which
  triggers the release pipeline) is an explicit `--push` step.

### Workflows that are intentionally skeletons

`workflow_dispatch`-only and gated behind the `production` GitHub Environment
(configure required reviewers). They contain **no real AWS steps** — the live
apply/install/upgrade is an `echo` placeholder until the cluster is provisioned:

- `deploy-dryrun.yml` — runs `helm lint` + `helm template` for real (offline),
  then a placeholder for the live cluster diff.
- `rollback.yml` — placeholder documenting the operator rollback.
- `release.yml` — builds/publishes images + chart to GHCR; the EKS deploy job is
  a gated placeholder (real steps kept commented).

### Explicitly NOT done

No `terraform apply`, no AWS resource creation, no live OIDC trust, no ECR
pushes, no Kubernetes deploys, no connection to any live cloud account.
