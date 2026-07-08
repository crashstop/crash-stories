.PHONY: all validate lint wrangle

all: validate lint wrangle

validate:
	python3 scripts/validate_stories.py

lint:
	python3 scripts/lint_stories.py

wrangle:
	python3 scripts/wrangle_stories.py
