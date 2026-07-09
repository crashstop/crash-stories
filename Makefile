.PHONY: all format lint wrangle

all: format lint wrangle

format:
	python3 scripts/format.py

lint:
	python3 scripts/lint.py

wrangle:
	python3 scripts/wrangle.py


reconcile:
	python3 scripts/reconcile.py
