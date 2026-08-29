# Thin wrapper around ./q, kept for muscle memory. `./q --help` is the real
# interface: it takes flags these targets can't (--all, --dry) and has an
# `archive` subcommand with no target here.
.PHONY: all format lint reconcile wrangle

all:
	./q make

format:
	./q format

lint:
	./q lint

reconcile:
	./q reconcile

wrangle:
	./q wrangle
