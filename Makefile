PYTHON ?= .venv/bin/python

.PHONY: install contracts openapi fixtures test test-cov stage0-demo stage0-fail stage0-injection real-smoke openai-convergence-dry-run openai-convergence-real openai-xhigh-qualification-dry-run openai-xhigh-qualification-real openai-max-qualification-dry-run openai-max-qualification-real openai-terra-medium-qualification-dry-run openai-terra-medium-qualification-real openai-canary-dry-run openai-p01-injection-recanary-dry-run openai-p02-v113-recanary-dry-run openai-p04-v116-recanary-dry-run openai-p05-v114-recanary-dry-run openai-blueprint-v119-v115-recanary-dry-run openai-blueprint-v117-v115-timeout-recovery-dry-run openai-p06-v112-decision-lineage-recanary-dry-run openai-p09-v115-recanary-dry-run openai-p11-v114-direct-dry-run openai-qualification-dry-run openai-qualification-v113-continuation-dry-run openai-qualification-v114-continuation-dry-run frontend-install frontend-typecheck frontend-test frontend-build postgres-prepare postgres-e2e postgres-sensitive postgres-stage2-recovery secrets-check

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

openai-convergence-dry-run:
	@env -u CVA_OPENAI_API_KEY $(PYTHON) scripts/run_openai_evals.py \
		--mode convergence-dry-run

openai-convergence-real:
	@test -n "$(EXECUTION_ID)" || { echo "EXECUTION_ID is required" >&2; exit 2; }
	@test -n "$(AUTHORIZATION_ID)" || { echo "AUTHORIZATION_ID is required" >&2; exit 2; }
	@test -n "$(LEDGER)" || { echo "LEDGER is required" >&2; exit 2; }
	@test -n "$(REPORT)" || { echo "REPORT is required" >&2; exit 2; }
	@test -n "$(SECRET_VERSION_RESOURCE)" || { echo "SECRET_VERSION_RESOURCE is required" >&2; exit 2; }
	@env -u CVA_OPENAI_API_KEY $(PYTHON) scripts/run_openai_evals.py \
		--mode convergence-real \
		--allow-billable \
		--execution-id "$(EXECUTION_ID)" \
		--authorization-id "$(AUTHORIZATION_ID)" \
		--ledger "$(LEDGER)" \
		--report-path "$(REPORT)" \
		--secret-version-resource "$(SECRET_VERSION_RESOURCE)" \
		--max-total-cost-usd "$${CVA_OPENAI_CONVERGENCE_MAX_TOTAL_USD:-0.75}" \
		--max-call-cost-usd "$${CVA_OPENAI_CONVERGENCE_MAX_CALL_USD:-0.10}" \
		--max-provider-requests 24

openai-xhigh-qualification-dry-run:
	@env -u CVA_OPENAI_API_KEY $(PYTHON) scripts/run_openai_evals.py \
		--mode xhigh-qualification-dry-run \
		--max-total-cost-usd 0.75 \
		--max-call-cost-usd 0.10 \
		--max-provider-requests 24

openai-xhigh-qualification-real:
	@test -n "$(EXECUTION_ID)" || { echo "EXECUTION_ID is required" >&2; exit 2; }
	@test -n "$(AUTHORIZATION_ID)" || { echo "AUTHORIZATION_ID is required" >&2; exit 2; }
	@test -n "$(LEDGER)" || { echo "LEDGER is required" >&2; exit 2; }
	@test -n "$(REPORT)" || { echo "REPORT is required" >&2; exit 2; }
	@test -n "$(SECRET_VERSION_RESOURCE)" || { echo "SECRET_VERSION_RESOURCE is required" >&2; exit 2; }
	@env -u CVA_OPENAI_API_KEY $(PYTHON) scripts/run_openai_evals.py \
		--mode xhigh-qualification-real \
		--allow-billable \
		--execution-id "$(EXECUTION_ID)" \
		--authorization-id "$(AUTHORIZATION_ID)" \
		--ledger "$(LEDGER)" \
		--report-path "$(REPORT)" \
		--secret-version-resource "$(SECRET_VERSION_RESOURCE)" \
		--max-total-cost-usd 0.75 \
		--max-call-cost-usd 0.10 \
		--max-provider-requests 24

openai-max-qualification-dry-run:
	@env -u CVA_OPENAI_API_KEY $(PYTHON) scripts/run_openai_evals.py \
		--mode max-qualification-dry-run \
		--max-total-cost-usd 0.75 \
		--max-call-cost-usd 0.10 \
		--max-provider-requests 24

openai-max-qualification-real:
	@test -n "$(EXECUTION_ID)" || { echo "EXECUTION_ID is required" >&2; exit 2; }
	@test -n "$(AUTHORIZATION_ID)" || { echo "AUTHORIZATION_ID is required" >&2; exit 2; }
	@test -n "$(LEDGER)" || { echo "LEDGER is required" >&2; exit 2; }
	@test -n "$(REPORT)" || { echo "REPORT is required" >&2; exit 2; }
	@test -n "$(SECRET_VERSION_RESOURCE)" || { echo "SECRET_VERSION_RESOURCE is required" >&2; exit 2; }
	@env -u CVA_OPENAI_API_KEY $(PYTHON) scripts/run_openai_evals.py \
		--mode max-qualification-real \
		--allow-billable \
		--execution-id "$(EXECUTION_ID)" \
		--authorization-id "$(AUTHORIZATION_ID)" \
		--ledger "$(LEDGER)" \
		--report-path "$(REPORT)" \
		--secret-version-resource "$(SECRET_VERSION_RESOURCE)" \
		--max-total-cost-usd 0.75 \
		--max-call-cost-usd 0.10 \
		--max-provider-requests 24

openai-terra-medium-qualification-dry-run:
	@env -u CVA_OPENAI_API_KEY $(PYTHON) scripts/run_openai_evals.py \
		--mode terra-medium-qualification-dry-run \
		--max-total-cost-usd 5.10 \
		--max-call-cost-usd 0.27 \
		--max-provider-requests 24

openai-terra-medium-qualification-real:
	@test -n "$(EXECUTION_ID)" || { echo "EXECUTION_ID is required" >&2; exit 2; }
	@test -n "$(AUTHORIZATION_ID)" || { echo "AUTHORIZATION_ID is required" >&2; exit 2; }
	@test -n "$(LEDGER)" || { echo "LEDGER is required" >&2; exit 2; }
	@test -n "$(REPORT)" || { echo "REPORT is required" >&2; exit 2; }
	@test -n "$(SECRET_VERSION_RESOURCE)" || { echo "SECRET_VERSION_RESOURCE is required" >&2; exit 2; }
	@env -u CVA_OPENAI_API_KEY $(PYTHON) scripts/run_openai_evals.py \
		--mode terra-medium-qualification-real \
		--allow-billable \
		--execution-id "$(EXECUTION_ID)" \
		--authorization-id "$(AUTHORIZATION_ID)" \
		--ledger "$(LEDGER)" \
		--report-path "$(REPORT)" \
		--secret-version-resource "$(SECRET_VERSION_RESOURCE)" \
		--max-total-cost-usd 5.10 \
		--max-call-cost-usd 0.27 \
		--max-provider-requests 24

openai-canary-dry-run:
	@test -n "$(CASE_ID)" || { echo "CASE_ID is required" >&2; exit 2; }
	@env -u CVA_OPENAI_API_KEY \
		-u CVA_OPENAI_REAL_EVALS_APPROVAL \
		-u CVA_OPENAI_LUNA_CANARY_APPROVAL \
		-u CVA_OPENAI_P01_INJECTION_RECANARY_APPROVAL \
		-u CVA_OPENAI_P01_INJECTION_V112_RECANARY_APPROVAL \
		-u CVA_OPENAI_P01_V112_REMEDIATION_DECISION \
		-u CVA_OPENAI_P02_V113_REMEDIATION_DECISION \
		-u CVA_OPENAI_P02_V113_RECANARY_APPROVAL \
		-u CVA_OPENAI_P04_V116_REMEDIATION_DECISION \
		-u CVA_OPENAI_P04_V116_RECANARY_APPROVAL \
		-u CVA_OPENAI_P04_V116_EVIDENCE_RECOVERY_APPROVAL \
		-u CVA_OPENAI_P05_V114_REMEDIATION_DECISION \
		-u CVA_OPENAI_P05_V114_RECANARY_APPROVAL \
		-u CVA_OPENAI_P09_V115_REMEDIATION_DECISION \
		-u CVA_OPENAI_P09_V115_RECANARY_APPROVAL \
		-u CVA_OPENAI_REAL_QUALIFICATION_APPROVAL \
		-u CVA_OPENAI_REAL_QUALIFICATION_V113_APPROVAL \
		-u CVA_OPENAI_REAL_QUALIFICATION_V113_CONTINUATION_APPROVAL \
		-u CVA_OPENAI_REAL_QUALIFICATION_V114_CONTINUATION_APPROVAL \
		$(PYTHON) scripts/run_openai_evals.py --mode canary-dry-run --case-id "$(CASE_ID)"

openai-p01-injection-recanary-dry-run:
	@env -u CVA_OPENAI_API_KEY \
		-u CVA_OPENAI_REAL_EVALS_APPROVAL \
		-u CVA_OPENAI_LUNA_CANARY_APPROVAL \
		-u CVA_OPENAI_P01_INJECTION_RECANARY_APPROVAL \
		-u CVA_OPENAI_P01_INJECTION_V112_RECANARY_APPROVAL \
		-u CVA_OPENAI_P01_V112_REMEDIATION_DECISION \
		-u CVA_OPENAI_P02_V113_REMEDIATION_DECISION \
		-u CVA_OPENAI_P02_V113_RECANARY_APPROVAL \
		-u CVA_OPENAI_P04_V116_REMEDIATION_DECISION \
		-u CVA_OPENAI_P04_V116_RECANARY_APPROVAL \
		-u CVA_OPENAI_P04_V116_EVIDENCE_RECOVERY_APPROVAL \
		-u CVA_OPENAI_P05_V114_REMEDIATION_DECISION \
		-u CVA_OPENAI_P05_V114_RECANARY_APPROVAL \
		-u CVA_OPENAI_P09_V115_REMEDIATION_DECISION \
		-u CVA_OPENAI_P09_V115_RECANARY_APPROVAL \
		-u CVA_OPENAI_REAL_QUALIFICATION_APPROVAL \
		-u CVA_OPENAI_REAL_QUALIFICATION_V113_APPROVAL \
		-u CVA_OPENAI_REAL_QUALIFICATION_V113_CONTINUATION_APPROVAL \
		-u CVA_OPENAI_REAL_QUALIFICATION_V114_CONTINUATION_APPROVAL \
		$(PYTHON) scripts/run_openai_evals.py --mode canary-dry-run --case-id "oa-p01-injection-md"

openai-p02-v113-recanary-dry-run:
	@env -u CVA_OPENAI_API_KEY \
		-u CVA_OPENAI_REAL_EVALS_APPROVAL \
		-u CVA_OPENAI_LUNA_CANARY_APPROVAL \
		-u CVA_OPENAI_P01_INJECTION_RECANARY_APPROVAL \
		-u CVA_OPENAI_P01_INJECTION_V112_RECANARY_APPROVAL \
		-u CVA_OPENAI_P01_V112_REMEDIATION_DECISION \
		-u CVA_OPENAI_P02_V113_REMEDIATION_DECISION \
		-u CVA_OPENAI_P02_V113_RECANARY_APPROVAL \
		-u CVA_OPENAI_P04_V116_REMEDIATION_DECISION \
		-u CVA_OPENAI_P04_V116_RECANARY_APPROVAL \
		-u CVA_OPENAI_P04_V116_EVIDENCE_RECOVERY_APPROVAL \
		-u CVA_OPENAI_P05_V114_REMEDIATION_DECISION \
		-u CVA_OPENAI_P05_V114_RECANARY_APPROVAL \
		-u CVA_OPENAI_P09_V115_REMEDIATION_DECISION \
		-u CVA_OPENAI_P09_V115_RECANARY_APPROVAL \
		-u CVA_OPENAI_REAL_QUALIFICATION_APPROVAL \
		-u CVA_OPENAI_REAL_QUALIFICATION_V113_APPROVAL \
		-u CVA_OPENAI_REAL_QUALIFICATION_V113_CONTINUATION_APPROVAL \
		-u CVA_OPENAI_REAL_QUALIFICATION_V114_CONTINUATION_APPROVAL \
		$(PYTHON) scripts/run_openai_evals.py --mode canary-dry-run --case-id "oa-p02-happy-pdf"

openai-p05-v114-recanary-dry-run:
	@env -u CVA_OPENAI_API_KEY \
		-u CVA_OPENAI_REAL_EVALS_APPROVAL \
		-u CVA_OPENAI_LUNA_CANARY_APPROVAL \
		-u CVA_OPENAI_P01_INJECTION_RECANARY_APPROVAL \
		-u CVA_OPENAI_P01_INJECTION_V112_RECANARY_APPROVAL \
		-u CVA_OPENAI_P01_V112_REMEDIATION_DECISION \
		-u CVA_OPENAI_P02_V113_REMEDIATION_DECISION \
		-u CVA_OPENAI_P02_V113_RECANARY_APPROVAL \
		-u CVA_OPENAI_P04_V116_REMEDIATION_DECISION \
		-u CVA_OPENAI_P04_V116_RECANARY_APPROVAL \
		-u CVA_OPENAI_P04_V116_EVIDENCE_RECOVERY_APPROVAL \
		-u CVA_OPENAI_P05_V114_REMEDIATION_DECISION \
		-u CVA_OPENAI_P05_V114_RECANARY_APPROVAL \
		-u CVA_OPENAI_P09_V115_REMEDIATION_DECISION \
		-u CVA_OPENAI_P09_V115_RECANARY_APPROVAL \
		-u CVA_OPENAI_REAL_QUALIFICATION_APPROVAL \
		-u CVA_OPENAI_REAL_QUALIFICATION_V113_APPROVAL \
		-u CVA_OPENAI_REAL_QUALIFICATION_V113_CONTINUATION_APPROVAL \
		-u CVA_OPENAI_REAL_QUALIFICATION_V114_CONTINUATION_APPROVAL \
		$(PYTHON) scripts/run_openai_evals.py --mode canary-dry-run --case-id "oa-p05-happy"

openai-p04-v116-recanary-dry-run:
	@env -u CVA_OPENAI_API_KEY \
		-u CVA_OPENAI_REAL_EVALS_APPROVAL \
		-u CVA_OPENAI_LUNA_CANARY_APPROVAL \
		-u CVA_OPENAI_P01_INJECTION_RECANARY_APPROVAL \
		-u CVA_OPENAI_P01_INJECTION_V112_RECANARY_APPROVAL \
		-u CVA_OPENAI_P01_V112_REMEDIATION_DECISION \
		-u CVA_OPENAI_P02_V113_REMEDIATION_DECISION \
		-u CVA_OPENAI_P02_V113_RECANARY_APPROVAL \
		-u CVA_OPENAI_P04_V116_REMEDIATION_DECISION \
		-u CVA_OPENAI_P04_V116_RECANARY_APPROVAL \
		-u CVA_OPENAI_P04_V116_EVIDENCE_RECOVERY_APPROVAL \
		-u CVA_OPENAI_P05_V114_REMEDIATION_DECISION \
		-u CVA_OPENAI_P05_V114_RECANARY_APPROVAL \
		-u CVA_OPENAI_P09_V115_REMEDIATION_DECISION \
		-u CVA_OPENAI_P09_V115_RECANARY_APPROVAL \
		-u CVA_OPENAI_P11_V114_DIRECT_APPROVAL \
		-u CVA_OPENAI_REAL_QUALIFICATION_APPROVAL \
		-u CVA_OPENAI_REAL_QUALIFICATION_V113_APPROVAL \
		-u CVA_OPENAI_REAL_QUALIFICATION_V113_CONTINUATION_APPROVAL \
		-u CVA_OPENAI_REAL_QUALIFICATION_V114_CONTINUATION_APPROVAL \
		$(PYTHON) scripts/run_openai_evals.py --mode canary-dry-run --case-id "oa-p04-happy"

openai-blueprint-v119-v115-recanary-dry-run:
	@env -u CVA_OPENAI_API_KEY \
		-u CVA_OPENAI_BLUEPRINT_V119_V115_REMEDIATION_DECISION \
		-u CVA_OPENAI_BLUEPRINT_V119_V115_RECANARY_APPROVAL \
		$(PYTHON) scripts/run_openai_evals.py --mode blueprint-recanary-dry-run

openai-blueprint-v117-v115-timeout-recovery-dry-run:
	@env -u CVA_OPENAI_API_KEY \
		-u CVA_OPENAI_BLUEPRINT_V117_V115_REMEDIATION_DECISION \
		-u CVA_OPENAI_BLUEPRINT_V117_V115_RECANARY_APPROVAL \
		-u CVA_OPENAI_BLUEPRINT_V117_V115_TIMEOUT_REMEDIATION_DECISION \
		-u CVA_OPENAI_BLUEPRINT_V117_V115_TIMEOUT_RECOVERY_APPROVAL \
		$(PYTHON) scripts/run_openai_evals.py --mode blueprint-timeout-recovery-dry-run

openai-p06-v112-decision-lineage-recanary-dry-run:
	@env -u CVA_OPENAI_API_KEY \
		-u CVA_OPENAI_P06_V112_DECISION_LINEAGE_RECANARY_APPROVAL \
		$(PYTHON) scripts/run_openai_evals.py --mode canary-dry-run --case-id "oa-p06-happy-docx"

openai-p09-v115-recanary-dry-run:
	@env -u CVA_OPENAI_API_KEY \
		-u CVA_OPENAI_REAL_EVALS_APPROVAL \
		-u CVA_OPENAI_LUNA_CANARY_APPROVAL \
		-u CVA_OPENAI_P01_INJECTION_RECANARY_APPROVAL \
		-u CVA_OPENAI_P01_INJECTION_V112_RECANARY_APPROVAL \
		-u CVA_OPENAI_P01_V112_REMEDIATION_DECISION \
		-u CVA_OPENAI_P02_V113_REMEDIATION_DECISION \
		-u CVA_OPENAI_P02_V113_RECANARY_APPROVAL \
		-u CVA_OPENAI_P04_V116_REMEDIATION_DECISION \
		-u CVA_OPENAI_P04_V116_RECANARY_APPROVAL \
		-u CVA_OPENAI_P04_V116_EVIDENCE_RECOVERY_APPROVAL \
		-u CVA_OPENAI_P05_V114_REMEDIATION_DECISION \
		-u CVA_OPENAI_P05_V114_RECANARY_APPROVAL \
		-u CVA_OPENAI_P09_V115_REMEDIATION_DECISION \
		-u CVA_OPENAI_P09_V115_RECANARY_APPROVAL \
		-u CVA_OPENAI_REAL_QUALIFICATION_APPROVAL \
		-u CVA_OPENAI_REAL_QUALIFICATION_V113_APPROVAL \
		-u CVA_OPENAI_REAL_QUALIFICATION_V113_CONTINUATION_APPROVAL \
		-u CVA_OPENAI_REAL_QUALIFICATION_V114_CONTINUATION_APPROVAL \
		$(PYTHON) scripts/run_openai_evals.py --mode canary-dry-run --case-id "oa-p09-happy-docx"

openai-p11-v114-direct-dry-run:
	@env -u CVA_OPENAI_API_KEY \
		-u CVA_OPENAI_REAL_EVALS_APPROVAL \
		-u CVA_OPENAI_LUNA_CANARY_APPROVAL \
		-u CVA_OPENAI_P01_INJECTION_RECANARY_APPROVAL \
		-u CVA_OPENAI_P01_INJECTION_V112_RECANARY_APPROVAL \
		-u CVA_OPENAI_P01_V112_REMEDIATION_DECISION \
		-u CVA_OPENAI_P02_V113_REMEDIATION_DECISION \
		-u CVA_OPENAI_P02_V113_RECANARY_APPROVAL \
		-u CVA_OPENAI_P04_V116_REMEDIATION_DECISION \
		-u CVA_OPENAI_P04_V116_RECANARY_APPROVAL \
		-u CVA_OPENAI_P04_V116_EVIDENCE_RECOVERY_APPROVAL \
		-u CVA_OPENAI_P05_V114_REMEDIATION_DECISION \
		-u CVA_OPENAI_P05_V114_RECANARY_APPROVAL \
		-u CVA_OPENAI_P09_V115_REMEDIATION_DECISION \
		-u CVA_OPENAI_P09_V115_RECANARY_APPROVAL \
		-u CVA_OPENAI_P11_V114_DIRECT_APPROVAL \
		-u CVA_OPENAI_REAL_QUALIFICATION_APPROVAL \
		-u CVA_OPENAI_REAL_QUALIFICATION_V113_APPROVAL \
		-u CVA_OPENAI_REAL_QUALIFICATION_V113_CONTINUATION_APPROVAL \
		-u CVA_OPENAI_REAL_QUALIFICATION_V114_CONTINUATION_APPROVAL \
		$(PYTHON) scripts/run_openai_evals.py --mode canary-dry-run --case-id "oa-p11-happy"

openai-qualification-v113-continuation-dry-run:
	@printf '%s\n' '{"code":"OPENAI_QUALIFICATION_V113_CONTINUATION_ALREADY_CONSUMED","network_calls":0,"status":"BLOCKED"}'
	@false

openai-qualification-dry-run openai-qualification-v114-continuation-dry-run:
	@env -u CVA_OPENAI_API_KEY \
		-u CVA_OPENAI_REAL_EVALS_APPROVAL \
		-u CVA_OPENAI_LUNA_CANARY_APPROVAL \
		-u CVA_OPENAI_P01_INJECTION_RECANARY_APPROVAL \
		-u CVA_OPENAI_P01_INJECTION_V112_RECANARY_APPROVAL \
		-u CVA_OPENAI_P01_V112_REMEDIATION_DECISION \
		-u CVA_OPENAI_P02_V113_REMEDIATION_DECISION \
		-u CVA_OPENAI_P02_V113_RECANARY_APPROVAL \
		-u CVA_OPENAI_P04_V116_REMEDIATION_DECISION \
		-u CVA_OPENAI_P04_V116_RECANARY_APPROVAL \
		-u CVA_OPENAI_P04_V116_EVIDENCE_RECOVERY_APPROVAL \
		-u CVA_OPENAI_P05_V114_REMEDIATION_DECISION \
		-u CVA_OPENAI_P05_V114_RECANARY_APPROVAL \
		-u CVA_OPENAI_P09_V115_REMEDIATION_DECISION \
		-u CVA_OPENAI_P09_V115_RECANARY_APPROVAL \
		-u CVA_OPENAI_REAL_QUALIFICATION_APPROVAL \
		-u CVA_OPENAI_REAL_QUALIFICATION_V113_APPROVAL \
		-u CVA_OPENAI_REAL_QUALIFICATION_V113_CONTINUATION_APPROVAL \
		-u CVA_OPENAI_REAL_QUALIFICATION_V114_CONTINUATION_APPROVAL \
		$(PYTHON) scripts/run_openai_evals.py --mode qualification-dry-run

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
