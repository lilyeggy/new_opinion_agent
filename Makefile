.PHONY: help install lint format typecheck test test-fast demo quality quality-check web clean

PYTHON ?= python3
PIP ?= $(PYTHON) -m pip
PYTEST ?= pytest
RUFF ?= ruff
MYPY ?= mypy

help:
	@echo "OpinionSearch Agent - Development Commands"
	@echo "==========================================="
	@echo "  make install    - Install package in editable mode with dev dependencies"
	@echo "  make lint       - Run ruff static analysis"
	@echo "  make format     - Run ruff code formatting"
	@echo "  make typecheck  - Run mypy type checking on runtime core"
	@echo "  make test-fast  - Run unit tests quickly"
	@echo "  make test       - Run full test suite"
	@echo "  make demo       - Run deterministic offline demo"
	@echo "  make quality    - Recompute the offline quality baseline (no model, no network)"
	@echo "  make quality-check - Verify the quality baseline reproduces exactly"
	@echo "  make web        - Launch local web workbench on port 8900"
	@echo "  make clean      - Clean up temporary test files and caches"

install:
	$(PIP) install -e 'opinion_search_agent[dev]'

lint:
	$(RUFF) check opinion_search_agent/src --config opinion_search_agent/pyproject.toml

format:
	$(RUFF) format opinion_search_agent/src --config opinion_search_agent/pyproject.toml

typecheck:
	$(MYPY) opinion_search_agent/src/opinion_search/runtime --ignore-missing-imports

test-fast:
	$(PYTEST) opinion_search_agent/tests/unit -q

test:
	mkdir -p opinion_search_agent/.pytest_tmp
	TMPDIR="$(PWD)/opinion_search_agent/.pytest_tmp" $(PYTEST) opinion_search_agent/tests -q -p no:cacheprovider

demo:
	cd opinion_search_agent && PYTHONPATH=src $(PYTHON) -m opinion_search offline \
		--question "What happened in the example event?" \
		--topic "Example event" \
		--focus "Compare event facts and causal accounts" \
		--run-id offline-demo \
		--checkpoint .opinion_search/offline-demo.json

quality:
	cd opinion_search_agent && PYTHONPATH=src $(PYTHON) scripts/quality_gate.py

quality-check:
	cd opinion_search_agent && PYTHONPATH=src $(PYTHON) scripts/quality_gate.py --check

web:
	cd opinion_search_agent && PYTHONPATH=src $(PYTHON) -m opinion_search.web --port 8900

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name "*.egg-info" -exec rm -rf {} +
	rm -rf opinion_search_agent/.pytest_tmp opinion_search_agent/.pytest_run opinion_search_agent/.pytest_iso2
	rm -rf .mypy_cache .pytest_cache .ruff_cache opinion_search_agent/.mypy_cache opinion_search_agent/.pytest_cache
