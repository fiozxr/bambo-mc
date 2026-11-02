# bambo-mc — developer task runner.
# Targets are safe to run repeatedly; `make live` is the only one that touches
# the real server (starts it, checks it, stops it again).

SHELL := /bin/bash

.PHONY: help lint test java-test smoke live clean bootstrap

help:
	@echo "bambo-mc — developer tasks"
	@echo ""
	@echo "  make lint        static checks (bash -n, py_compile, shellcheck if present)"
	@echo "  make test        run the non-live test suite (tests/run.sh)"
	@echo "  make java-test   build empty-serve and run all layer self-tests + probes"
	@echo "  make smoke       dashboard smoke test on a scratch port (start/stop it)"
	@echo "  make live        full live cycle: doctor, health, up, status, down"
	@echo "  make bootstrap    automatic setup: deps, jar, wrappers, cron, token, dash"
	@echo "  make clean       remove java build output"

lint:
	@set -e; \
	bash -n bambo install.sh bin/bambo-nettest; \
	python3 -m py_compile bin/bambo-dash.py; \
	if command -v shellcheck >/dev/null 2>&1; then \
	  shellcheck --severity=warning -x bambo install.sh bin/bambo-nettest; \
	else echo "  (shellcheck not installed — skipped; install it for stricter lint)"; fi
	@echo "lint: OK"

test:
	@bash tests/run.sh

java-test:
	@bash empty-serve/run-tests.sh

smoke:
	@bash tests/dash_smoke.sh

bootstrap:
	@bash install.sh --auto

live:
	@set -e; \
	./bambo doctor; \
	./bambo health --json; \
	./bambo up; \
	sleep 40; \
	./bambo status; \
	./bambo down

clean:
	@rm -rf empty-serve/out
	@echo "cleaned java build output"
