# Makefile — commandes usuelles (à adapter sous Windows : utiliser `make` ou les commandes listées).

PYTHON ?= python
FILE ?= "D:/DevSources/Ores_Digest/Rapport mensuel ORES - 2026-08-03 - 0306 PM.xlsx"

.PHONY: install init-db import fetch rebuild validate api ui test lint

install:
	$(PYTHON) -m pip install -e ".[dev]"

init-db:
	$(PYTHON) -m app.cli init-db

import:
	$(PYTHON) -m app.cli import-excel --file $(FILE)

fetch:
	$(PYTHON) -m app.cli fetch-prices

rebuild:
	$(PYTHON) -m app.cli rebuild-aggregates

validate:
	$(PYTHON) -m app.cli validate

api:
	uvicorn app.api:app --reload

ui:
	streamlit run app/dashboard.py

test:
	pytest

lint:
	ruff check app tests
