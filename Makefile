.PHONY: help build up dev down restart stop logs logs-web logs-db shell bash dbshell migrate makemigrations createsuperuser import test lint format typecheck clean clean-all version bump-patch bump-minor bump-major deploy backup
.DEFAULT_GOAL := help

DC := docker compose -f docker-compose.dev.yml
UV := uv run --extra dev

PYPROJECT := pyproject.toml
VERSION := $(shell grep -m1 'version = ' $(PYPROJECT) | cut -d'"' -f2)
MAJOR := $(shell echo $(VERSION) | cut -d. -f1)
MINOR := $(shell echo $(VERSION) | cut -d. -f2)
PATCH := $(shell echo $(VERSION) | cut -d. -f3)

# Default target
help:
	@echo "ENEROOO Spark Device Library Commands"
	@echo "====================================="
	@echo ""
	@echo "Setup:"
	@echo "  make build          - Build Docker images"
	@echo ""
	@echo "Control:"
	@echo "  make up             - Start dev environment"
	@echo "  make dev            - Alias for 'make up'"
	@echo "  make down           - Stop all services"
	@echo "  make restart        - Restart all services"
	@echo "  make stop           - Stop services without removing"
	@echo ""
	@echo "Development:"
	@echo "  make logs           - View logs (all services)"
	@echo "  make logs-web       - View web container logs"
	@echo "  make logs-db        - View database logs"
	@echo "  make shell          - Django shell"
	@echo "  make bash           - Bash shell in web container"
	@echo ""
	@echo "Database:"
	@echo "  make migrate        - Run database migrations"
	@echo "  make makemigrations - Create new migrations"
	@echo "  make createsuperuser - Create Django superuser"
	@echo "  make dbshell        - PostgreSQL shell"
	@echo "  make import         - Import YAML device definitions into database"
	@echo "  make backup         - Backup production PostgreSQL database"
	@echo ""
	@echo "Quality:"
	@echo "  make test           - Run tests (pass extra args via ARGS=...)"
	@echo "  make lint           - Ruff check"
	@echo "  make format         - Ruff format"
	@echo "  make typecheck      - Mypy"
	@echo ""
	@echo "Cleanup:"
	@echo "  make clean          - Remove containers and volumes"
	@echo "  make clean-all      - Remove everything including images"
	@echo ""
	@echo "Release:"
	@echo "  make version        - Show current version ($(VERSION))"
	@echo "  make bump-patch     - Bump patch version ($(VERSION) → $(MAJOR).$(MINOR).$$(($(PATCH)+1)))"
	@echo "  make bump-minor     - Bump minor version ($(VERSION) → $(MAJOR).$$(($(MINOR)+1)).0)"
	@echo "  make bump-major     - Bump major version ($(VERSION) → $$(($(MAJOR)+1)).0.0)"
	@echo "  make deploy         - Push and create release PR (HEAD must be tagged)"

# Build
build:
	$(DC) build

# Control
up:
	$(DC) up -d
	@echo "✓ Services started"
	@echo "✓ Web: http://localhost:8005"
	@echo "✓ Admin: http://localhost:8005/admin/"
	@echo "✓ PostgreSQL: localhost:5435"

dev: up

down:
	$(DC) down

restart:
	$(DC) restart

stop:
	$(DC) stop

# Logs
logs:
	$(DC) logs -f -n 1000

logs-web:
	$(DC) logs -f web

logs-db:
	$(DC) logs -f db

# Shell access
shell:
	$(DC) exec web python manage.py shell

bash:
	$(DC) exec web bash

dbshell:
	$(DC) exec db psql -U spark_device_library -d spark_device_library

# Database
migrate:
	$(DC) exec web python manage.py migrate

makemigrations:
	$(DC) exec web python manage.py makemigrations

createsuperuser:
	$(DC) exec web python manage.py createsuperuser

import:
	$(DC) exec web python manage.py import_yaml --path /app/devices/ --manifest /app/manifest.yaml

backup:
	./scripts/backup-db.sh

# Quality — the dev image carries production deps only, so these run on the host
test:
	$(UV) pytest $(ARGS)

lint:
	$(UV) ruff check .

format:
	$(UV) ruff format .

typecheck:
	$(UV) mypy src

# Cleanup
clean:
	$(DC) down -v
	@echo "✓ Containers and volumes removed"

clean-all:
	$(DC) down -v --rmi all
	@echo "✓ Everything removed (containers, volumes, images)"

# Release
version:
	@echo $(VERSION)

bump-patch:
	$(eval NEW_VERSION := $(MAJOR).$(MINOR).$(shell echo $$(($(PATCH)+1))))
	@$(MAKE) --no-print-directory _bump NEW_VERSION=$(NEW_VERSION)

bump-minor:
	$(eval NEW_VERSION := $(MAJOR).$(shell echo $$(($(MINOR)+1))).0)
	@$(MAKE) --no-print-directory _bump NEW_VERSION=$(NEW_VERSION)

bump-major:
	$(eval NEW_VERSION := $(shell echo $$(($(MAJOR)+1))).0.0)
	@$(MAKE) --no-print-directory _bump NEW_VERSION=$(NEW_VERSION)

.PHONY: _bump
_bump:
	@echo "Bumping version: $(VERSION) → $(NEW_VERSION)"
	@sed -i '' 's/version = "$(VERSION)"/version = "$(NEW_VERSION)"/' $(PYPROJECT)
	git add $(PYPROJECT)
	git commit -m "Bump version to $(NEW_VERSION)"
	git tag -a "v$(NEW_VERSION)" -m "Release v$(NEW_VERSION)"
	@echo "✓ Bumped, committed and tagged v$(NEW_VERSION)"

deploy:
	@# Verify HEAD is tagged with a version
	$(eval TAG := $(shell git tag --points-at HEAD | grep '^v' | head -1))
	@if [ -z "$(TAG)" ]; then \
		echo "Error: HEAD is not tagged with a version."; \
		echo "Run 'make bump-patch' (or bump-minor/bump-major) first."; \
		exit 1; \
	fi
	$(eval DEPLOY_VERSION := $(TAG:v%=%))
	@echo "Deploying $(DEPLOY_VERSION)..."
	git push origin main --tags
	@echo "Closing any existing release PR..."
	-gh pr close main --base production --delete-branch=false 2>/dev/null
	@echo "Creating release PR..."
	gh pr create --base production --head main \
		--title "Release $(DEPLOY_VERSION)" \
		--body "Automated release PR for v$(DEPLOY_VERSION)"
