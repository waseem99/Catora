SHELL := /bin/bash

.PHONY: install dev up down test check migrate

install:
	npm install --no-audit --no-fund
	python3 -m pip install -e 'apps/api[dev]'

dev:
	npm run dev

up:
	docker compose up --build

down:
	docker compose down

test:
	npm test
	python3 -m pytest apps/api/tests

check:
	npm run check
	python3 -m ruff check apps/api
	python3 -m mypy --config-file apps/api/pyproject.toml apps/api/catora_api
	python3 -m pytest apps/api/tests

migrate:
	cd apps/api && alembic upgrade head
