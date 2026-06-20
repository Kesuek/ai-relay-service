.PHONY: dev test lint format install deploy migrate clean

VENV := .venv
PYTHON := $(VENV)/bin/python3
PIP := $(VENV)/bin/pip
RUFF := $(VENV)/bin/ruff
PYTEST := $(VENV)/bin/pytest
UVICORN := $(VENV)/bin/uvicorn
SERVICE := ai-relay-service

install:
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -e ".[dev]"

dev:
	$(UVICORN) relay_server.main:app --host 0.0.0.0 --port 8788 --reload --log-level info

test:
	$(PYTEST) -q

lint:
	$(RUFF) check src tests

format:
	$(RUFF) format src tests

migrate:
	$(PYTHON) -m relay_server.main --help >/dev/null

deploy:
	mkdir -p ~/.config/systemd/user
	cp systemd/ai-relay-service.service ~/.config/systemd/user/
	systemctl --user daemon-reload
	systemctl --user enable $(SERVICE)
	systemctl --user restart $(SERVICE)
	@echo "Status:"
	systemctl --user status $(SERVICE) --no-pager

logs:
	journalctl --user -u $(SERVICE) -f

clean:
	find src -type d -name __pycache__ -exec rm -rf {} +
	find src -type f -name "*.pyc" -delete
	rm -f .coverage
