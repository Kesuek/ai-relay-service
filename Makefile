.PHONY: dev test deploy migrate lint fmt clean

VENV := .venv
PYTHON := $(VENV)/bin/python3
PIP := $(VENV)/bin/pip
UVICORN := $(VENV)/bin/uvicorn

$(VENV):
	python3 -m venv $(VENV)
	$(PIP) install -e ".[dev]"

dev: $(VENV)
	$(UVICORN) relay_server.main:app --reload --port 8788 --host 0.0.0.0

test: $(VENV)
	$(PYTHON) -m pytest tests/ -v

migrate: $(VENV)
	$(PYTHON) scripts/init_db.py

deploy:
	systemctl --user daemon-reload
	systemctl --user enable ai-relay-service
	systemctl --user restart ai-relay-service

lint: $(VENV)
	$(VENV)/bin/ruff check src/ tests/

fmt: $(VENV)
	$(VENV)/bin/ruff format src/ tests/

clean:
	rm -rf $(VENV) build/ dist/ *.egg-info
	rm -f .coverage
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
