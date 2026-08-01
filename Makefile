PYTHON ?= .venv/bin/python

.PHONY: install contracts fixtures test test-cov stage0-demo stage0-fail stage0-injection real-smoke

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

