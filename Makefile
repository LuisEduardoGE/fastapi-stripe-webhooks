PYTHON ?= python
PORT ?= 8000
IMAGE ?= fastapi-stripe-webhooks
PIP_ARGS ?=
DOCKER_BUILD_ARGS ?=

.DEFAULT_GOAL := help
.PHONY: help install run test lint clean docker-build docker-run

help: ## List available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-14s %s\n", $$1, $$2}'

install: ## Install app and dev dependencies
	$(PYTHON) -m pip install $(PIP_ARGS) -r requirements-dev.txt

run: ## Run the API with reload on PORT (default 8000)
	$(PYTHON) -m uvicorn app.main:create_app --factory --reload --port $(PORT)

test: ## Run the test suite
	$(PYTHON) -m pytest -q

lint: ## Lint and check formatting with ruff
	$(PYTHON) -m ruff check .
	$(PYTHON) -m ruff format --check .

clean: ## Remove caches and local SQLite files
	rm -rf .pytest_cache .ruff_cache *.db
	find . -path ./.venv -prune -o -name __pycache__ -type d -exec rm -rf {} +

docker-build: ## Build the Docker image
	docker build $(DOCKER_BUILD_ARGS) -t $(IMAGE) .

docker-run: ## Run the image on PORT (needs STRIPE_WEBHOOK_SECRET in the environment)
	docker run --rm -p $(PORT):8000 -e STRIPE_WEBHOOK_SECRET $(IMAGE)
