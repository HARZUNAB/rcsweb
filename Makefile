SHELL := /bin/bash
COMPOSE := docker compose

.PHONY: help up down logs ps shell test lint fmt init-db ping-db restore-csn clean

help:
	@echo "Objetivos disponibles:"
	@echo "  make up          Levanta web, worker, db y redis"
	@echo "  make down        Detiene los servicios (conserva datos)"
	@echo "  make logs        Sigue los logs de todos los servicios"
	@echo "  make ps          Estado de los servicios"
	@echo "  make shell       Shell dentro del contenedor web"
	@echo "  make test        Ejecuta la suite de tests"
	@echo "  make lint        Ruff check"
	@echo "  make fmt         Ruff format"
	@echo "  make init-db     Crea tablas y usuario administrador"
	@echo "  make ping-db     SELECT 1 contra la base rcs"
	@echo "  make restore-csn Restaura el dump csn_test (etapa 6a)"
	@echo "  make clean       Baja servicios y borra volúmenes"

up:
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f

ps:
	$(COMPOSE) ps

shell:
	$(COMPOSE) exec web bash

test:
	.venv/bin/pytest

lint:
	.venv/bin/ruff check .

fmt:
	.venv/bin/ruff format .

venv:
	python3.12 -m venv .venv
	.venv/bin/pip install -e ".[dev]"

init-db:
	$(COMPOSE) exec web flask --app app init-db

ping-db:
	$(COMPOSE) exec db psql -U $${POSTGRES_USER:-rcs} -d $${POSTGRES_DB:-rcs} -c "SELECT 1;"

restore-csn:
	$(COMPOSE) exec -T db pg_restore --username $${POSTGRES_USER:-rcs} \
		--dbname csn_test --no-owner /data/csn.dump

clean:
	$(COMPOSE) down -v
