.PHONY: all format lint wrangle

all: lint format wrangle

format:
	python3 scripts/format.py

lint:
	python3 scripts/lint.py

wrangle:
	python3 scripts/wrangle.py


reconcile:
	python3 scripts/reconcile.py
