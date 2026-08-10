PYTHON ?= .venv/bin/python

.PHONY: install contracts openapi fixtures test test-cov stage0-demo stage0-fail stage0-injection real-smoke openai-canary-dry-run frontend-install frontend-typecheck frontend-test frontend-build postgres-prepare postgres-e2e postgres-sensitive postgres-stage2-recovery secrets-check

install:
	$(PYTHON) -m pip install -e '.[dev]'

contracts:
	$(PYTHON) -m comprehension_verification.cli validate-contracts

openapi:
	$(PYTHON) scripts/generate_openapi.py

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

openai-canary-dry-run:
	@test -n "$(CASE_ID)" || { echo "CASE_ID is required" >&2; exit 2; }
	@env -u CVA_OPENAI_API_KEY \
		-u CVA_OPENAI_REAL_EVALS_APPROVAL \
		-u CVA_OPENAI_LUNA_CANARY_APPROVAL \
		$(PYTHON) scripts/run_openai_evals.py --mode canary-dry-run --case-id "$(CASE_ID)"

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

postgres-sensitive:
	CVA_TEST_DATABASE_URL="$${CVA_TEST_POSTGRES_URL}" $(PYTHON) -m pytest tests/test_stage1_postgres.py

postgres-stage2-recovery:
	$(PYTHON) -m pytest tests/test_stage2_migration.py tests/test_stage2_readiness.py

secrets-check:
	$(PYTHON) scripts/check_secrets.py
