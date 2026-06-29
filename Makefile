# Touchstone developer entrypoints. `make help` lists targets.
.DEFAULT_GOAL := help
CP := services/control-plane
VENV := .venv/bin

.PHONY: help
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-18s\033[0m %s\n",$$1,$$2}'

.PHONY: install
install: ## Create venv and install all packages (editable, with dev deps)
	python3 -m venv .venv
	$(VENV)/pip install -q -e ./libs/touchstone-events
	$(VENV)/pip install -q -e "./$(CP)[dev]"
	$(VENV)/pip install -q -e "./services/verification-engine[dev]"
	$(VENV)/pip install -q -e "./services/risk-engine[dev]"
	$(VENV)/pip install -q -e "./services/audit-engine[dev]"
	$(VENV)/pip install -q -e "./services/reward-hacking-detector[dev]"
	$(VENV)/pip install -q -e "./sdks/python[dev]"

.PHONY: demo
demo: ## Run the end-to-end demo against a running stack (see README)
	$(VENV)/python scripts/demo.py

.PHONY: up
up: ## Start the full local stack (Postgres, Redis, Redpanda, API)
	docker compose up --build -d

.PHONY: down
down: ## Stop the local stack
	docker compose down

.PHONY: migrate
migrate: ## Apply DB migrations to the configured database
	cd $(CP) && PYTHONPATH=src ../../$(VENV)/alembic upgrade head

.PHONY: revision
revision: ## Autogenerate a migration: make revision m="message"
	cd $(CP) && PYTHONPATH=src ../../$(VENV)/alembic revision --autogenerate -m "$(m)"

.PHONY: test
test: ## Run the full test suite across all packages
	cd $(CP) && PYTHONPATH=src ../../$(VENV)/python -m pytest tests/ -q
	cd services/verification-engine && PYTHONPATH=src ../../$(VENV)/python -m pytest tests/ -q
	cd services/risk-engine && PYTHONPATH=src ../../$(VENV)/python -m pytest tests/ -q
	cd services/audit-engine && PYTHONPATH=src ../../$(VENV)/python -m pytest tests/ -q
	cd services/reward-hacking-detector && PYTHONPATH=src ../../$(VENV)/python -m pytest tests/ -q
	cd sdks/python && PYTHONPATH=src ../../$(VENV)/python -m pytest tests/ -q

.PHONY: test-unit
test-unit: ## Run only unit tests (no infra required)
	cd $(CP) && PYTHONPATH=src ../../$(VENV)/python -m pytest tests/unit -q

.PHONY: load-smoke
load-smoke: ## Run the Locust smoke load profile (needs the control-plane running)
	cd load-tests && ./run.sh smoke

.PHONY: load-local
load-local: ## Run the Locust local load profile (needs the control-plane running)
	cd load-tests && ./run.sh local

.PHONY: lint
lint: ## Lint + type-check
	$(VENV)/ruff check $(CP)/src
	$(VENV)/mypy $(CP)/src

.PHONY: fmt
fmt: ## Auto-format and fix lint
	$(VENV)/ruff format $(CP)/src
	$(VENV)/ruff check --fix $(CP)/src

.PHONY: run
run: ## Run the API locally with autoreload (needs Postgres+Redis up)
	cd $(CP) && PYTHONPATH=src ../../$(VENV)/uvicorn touchstone_control.main:app --reload
