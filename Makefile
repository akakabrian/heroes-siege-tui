.PHONY: all bootstrap engine venv run test test-only perf clean

# Clean-room Python reimpl — there's no engine to build and nothing to
# vendor. `bootstrap` and `engine` are no-ops kept for skill-layout
# parity.
all: venv

bootstrap:
	@echo "==> no upstream to fetch (clean-room Python reimpl; see DECISIONS.md §1)"

engine:
	@echo "==> engine target is a no-op for homm2-tui"

venv: .venv/bin/python
.venv/bin/python:
	python3 -m venv .venv
	.venv/bin/pip install -e .

run: venv
	.venv/bin/python homm2.py

test: venv
	.venv/bin/python -m tests.qa
	.venv/bin/python -m tests.perf

test-only: venv
	.venv/bin/python -m tests.qa $(PAT)

perf: venv
	.venv/bin/python -m tests.perf

clean:
	rm -rf .venv homm2_tui/__pycache__ tests/__pycache__
