# Thin wrapper around ./cli, kept for muscle memory. `./cli --help` is the real
# interface: it takes flags these targets can't (--all, --dry) and has an
# `archive` subcommand with no target here.
.PHONY: all format lint reconcile wrangle

all:
	./cli make

format:
	./cli format

lint:
	./cli lint

reconcile:
	./cli reconcile

wrangle:
	./cli wrangle
