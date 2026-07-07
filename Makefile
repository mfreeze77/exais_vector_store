SHELL := /bin/bash
PYTHONPATH := packages/svs_common:apps/api:apps/worker:apps/model_gateway:apps/instance_agent
PROJECT_NAME := exai_vector_store
PROJECT_DIR := $(notdir $(CURDIR))
export PYTHONPATH

.PHONY: bootstrap up down logs migrate smoke test zip

bootstrap:
	@mkdir -p data/postgres data/redis data/qdrant data/opensearch data/minio backups
	@echo "Bootstrap complete."

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f --tail=200

migrate:
	./scripts/migrate.sh

smoke:
	./scripts/smoke-test.sh

test:
	python -m compileall packages apps tests
	pytest -q

zip:
	cd .. && zip -r $(PROJECT_NAME).zip $(PROJECT_DIR) -x '*/__pycache__/*' '*.pyc' '$(PROJECT_DIR)/data/*' '$(PROJECT_DIR)/backups/*'
