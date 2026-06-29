# Touchstone developer entrypoints (Linux/macOS). `make help` lists targets.
# Windows users: run the mirror wrapper instead — `./make.ps1 <target>`.
.DEFAULT_GOAL := help
SHELL := /bin/bash

CP := services/control-plane
VENV := .venv/bin
PY := $(VENV)/python
COMPOSE := docker compose

# Packages that keep unit and integration tests apart under tests/unit + tests/integration.
SERVICE_PKGS := services/control-plane services/verification-engine services/risk-engine \
                services/audit-engine services/reward-hacking-detector services/ivp
# Packages whose tests/ tree is flat (unit-level; infra-dependent cases skip themselves).
FLAT_PKGS := libs/touchstone-events libs/touchstone-fleet sdks/python

# ruff is configured per-package (line-length etc.), so it must run from each
# package dir. These mirror the CI lint scopes exactly.
RUFF_SRC := services/control-plane services/verification-engine services/risk-engine services/audit-engine
RUFF_SRC_TESTS := services/reward-hacking-detector services/ivp libs/touchstone-events libs/touchstone-fleet sdks/python

.PHONY: help
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-18s\033[0m %s\n",$$1,$$2}'

# --- environment ------------------------------------------------------------
.PHONY: install
install: ## Create venv and install all packages (editable, with dev deps)
	python3 -m venv .venv
	$(VENV)/pip install -q -e ./libs/touchstone-events
	$(VENV)/pip install -q -e ./libs/touchstone-fleet
	$(VENV)/pip install -q -e "./$(CP)[dev]"
	$(VENV)/pip install -q -e "./services/verification-engine[dev]"
	$(VENV)/pip install -q -e "./services/risk-engine[dev]"
	$(VENV)/pip install -q -e "./services/audit-engine[dev]"
	$(VENV)/pip install -q -e "./services/reward-hacking-detector[dev]"
	$(VENV)/pip install -q -e "./services/ivp[dev]"
	$(VENV)/pip install -q -e "./sdks/python[dev]"

# --- one-command lifecycle (Docker stack) -----------------------------------
.PHONY: build
build: ## Build every service image
	$(COMPOSE) build

.PHONY: up
up: ## Start the full local stack (Postgres, Redis, Redpanda, all services)
	$(COMPOSE) up --build -d

.PHONY: down
down: ## Stop the local stack (keeps volumes)
	$(COMPOSE) down

.PHONY: restart
restart: ## Restart the full stack
	$(COMPOSE) down
	$(COMPOSE) up --build -d

.PHONY: rebuild
rebuild: ## Rebuild images from scratch and recreate the stack
	$(COMPOSE) build --no-cache
	$(COMPOSE) up -d --force-recreate

.PHONY: health
health: ## Poll every service health endpoint and print a pass/fail table
	@./scripts/health.sh

# --- quality gates ----------------------------------------------------------
.PHONY: lint
lint: ## Lint every package with ruff (per-package config, CI scopes)
	@set -e; for p in $(RUFF_SRC); do echo "== ruff: $$p =="; ( cd $$p && ../../$(VENV)/ruff check src ); done
	@set -e; for p in $(RUFF_SRC_TESTS); do echo "== ruff: $$p =="; ( cd $$p && ../../$(VENV)/ruff check src tests ); done

.PHONY: typecheck
typecheck: ## Type-check the typed surface with mypy (run from the package dir)
	cd $(CP) && PYTHONPATH=src ../../$(VENV)/mypy src

.PHONY: fmt
fmt: ## Auto-format and fix lint (control-plane)
	$(VENV)/ruff format $(CP)/src
	$(VENV)/ruff check --fix $(CP)/src

.PHONY: test
test: ## Run the FULL suite across all packages (integration needs the stack up)
	@set -e; for p in $(SERVICE_PKGS) $(FLAT_PKGS); do echo "== pytest: $$p =="; ( cd $$p && PYTHONPATH=src ../../$(VENV)/python -m pytest tests -q ); done

.PHONY: test-unit
test-unit: ## Run unit tests across all packages (no infra; sandbox tests self-skip)
	@set -e; for p in $(SERVICE_PKGS); do echo "== unit: $$p =="; ( cd $$p && PYTHONPATH=src ../../$(VENV)/python -m pytest tests/unit -q ); done
	@set -e; for p in $(FLAT_PKGS); do echo "== unit: $$p =="; ( cd $$p && PYTHONPATH=src ../../$(VENV)/python -m pytest tests -q ); done

# --- infra validation (offline; no live cloud) ------------------------------
.PHONY: compose-validate
compose-validate: ## Validate docker-compose config
	$(COMPOSE) config --quiet && echo "docker compose config: OK"

.PHONY: validate-infra
validate-infra: ## Offline infra preflight (compose, terraform, helm, k8s)
	@./scripts/preflight.sh

# --- migrations / run / demo (unchanged) ------------------------------------
.PHONY: migrate
migrate: ## Apply DB migrations to the configured database
	cd $(CP) && PYTHONPATH=src ../../$(VENV)/alembic upgrade head

.PHONY: revision
revision: ## Autogenerate a migration: make revision m="message"
	cd $(CP) && PYTHONPATH=src ../../$(VENV)/alembic revision --autogenerate -m "$(m)"

.PHONY: run
run: ## Run the API locally with autoreload (needs Postgres+Redis up)
	cd $(CP) && PYTHONPATH=src ../../$(VENV)/uvicorn touchstone_control.main:app --reload

.PHONY: demo
demo: ## Run the end-to-end demo against a running stack (see README)
	$(VENV)/python scripts/demo.py

.PHONY: load-smoke
load-smoke: ## Run the Locust smoke load profile (needs the control-plane running)
	cd load-tests && ./run.sh smoke

.PHONY: load-local
load-local: ## Run the Locust local load profile (needs the control-plane running)
	cd load-tests && ./run.sh local

# --- whole-workflow + cleanup ----------------------------------------------
.PHONY: all
all: lint typecheck test-unit compose-validate ## Run the complete verifiable workflow (lint + types + unit tests + compose validation)
	@echo "✓ all: lint + typecheck + unit tests + compose config all green"

.PHONY: clean
clean: ## Tear down the stack (with volumes) and remove caches/venv/artifacts
	-$(COMPOSE) down -v --remove-orphans
	rm -rf .venv
	find . -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name '.pytest_cache' -prune -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name '.mypy_cache' -prune -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name '.ruff_cache' -prune -exec rm -rf {} + 2>/dev/null || true
	rm -rf apps/web/.next apps/web/node_modules sdks/typescript/node_modules sdks/typescript/dist
	find . -type f \( -name '.coverage' -o -name 'coverage.xml' -o -name 'junit.xml' \) -delete 2>/dev/null || true
	find . -type d -name reports -prune -exec rm -rf {} + 2>/dev/null || true
	rm -f rendered.yaml
	find .artifacts -mindepth 1 -not -name '.gitkeep' -delete 2>/dev/null || true
	@echo "✓ clean: stack, volumes, caches, venv, node_modules and artifacts removed"
