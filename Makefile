PYTHON ?= .venv/bin/python

.PHONY: install contracts fixtures test test-cov stage0-demo stage0-fail stage0-injection real-smoke frontend-install frontend-typecheck frontend-test frontend-build postgres-prepare postgres-e2e

install:
	$(PYTHON) -m pip install -e '.[dev]'

contracts:
	$(PYTHON) -m comprehension_verification.cli validate-contracts

fixtures:
	$(PYTHON) -m comprehension_verification.cli build-fixtures

test:
	$(PYTHON) -m pytest

test-cov:
	$(PYTHON) -m pytest --cov --cov-report=term-missing

stage0-demo:
	$(PYTHON) -m comprehension_verification.cli run-synthetic --case sufficient --output outputs/stage0-demo

stage0-fail:
	$(PYTHON) -m comprehension_verification.cli run-synthetic --case insufficient --output outputs/stage0-insufficient

stage0-injection:
	$(PYTHON) -m comprehension_verification.cli run-synthetic --case injection --output outputs/stage0-injection

real-smoke:
	$(PYTHON) -m comprehension_verification.cli real-provider-smoke --budget-usd "$${CVA_REAL_SMOKE_BUDGET_USD:-0}"

frontend-install:
	cd frontend && npm ci

frontend-typecheck:
	cd frontend && npm run typecheck

frontend-test:
	cd frontend && npm run test

frontend-build:
	cd frontend && npm run build

postgres-prepare:
	$(PYTHON) scripts/prepare_postgres.py --database-url "$${CVA_TEST_POSTGRES_URL}"

postgres-e2e:
	CVA_TEST_DATABASE_URL="$${CVA_TEST_POSTGRES_URL}" $(PYTHON) -m pytest tests/test_stage1_web.py::test_stage1_single_submission_mock_e2e_survives_new_browser_session
