.PHONY: version bump-patch bump-minor bump-major deploy dev dev-build dev-logs dev-down dev-migrate dev-shell dev-import backup help
.DEFAULT_GOAL := help

PYPROJECT := pyproject.toml

# Extract current version
VERSION := $(shell grep -m1 'version = ' $(PYPROJECT) | cut -d'"' -f2)
MAJOR := $(shell echo $(VERSION) | cut -d. -f1)
MINOR := $(shell echo $(VERSION) | cut -d. -f2)
PATCH := $(shell echo $(VERSION) | cut -d. -f3)

# === Version management ===

version:
	@echo $(VERSION)

bump-patch:
	$(eval NEW_VERSION := $(MAJOR).$(MINOR).$(shell echo $$(($(PATCH)+1))))
	@echo "Bumping version: $(VERSION) → $(NEW_VERSION)"
	@sed -i '' 's/version = "$(VERSION)"/version = "$(NEW_VERSION)"/' $(PYPROJECT)
	git add $(PYPROJECT)
	git commit -m "Bump version to $(NEW_VERSION)"
	git tag -a "v$(NEW_VERSION)" -m "Release v$(NEW_VERSION)"
	@echo "Bumped, committed and tagged v$(NEW_VERSION)"

bump-minor:
	$(eval NEW_VERSION := $(MAJOR).$(shell echo $$(($(MINOR)+1))).0)
	@echo "Bumping version: $(VERSION) → $(NEW_VERSION)"
	@sed -i '' 's/version = "$(VERSION)"/version = "$(NEW_VERSION)"/' $(PYPROJECT)
	git add $(PYPROJECT)
	git commit -m "Bump version to $(NEW_VERSION)"
	git tag -a "v$(NEW_VERSION)" -m "Release v$(NEW_VERSION)"
	@echo "Bumped, committed and tagged v$(NEW_VERSION)"

bump-major:
	$(eval NEW_VERSION := $(shell echo $$(($(MAJOR)+1))).0.0)
	@echo "Bumping version: $(VERSION) → $(NEW_VERSION)"
	@sed -i '' 's/version = "$(VERSION)"/version = "$(NEW_VERSION)"/' $(PYPROJECT)
	git add $(PYPROJECT)
	git commit -m "Bump version to $(NEW_VERSION)"
	git tag -a "v$(NEW_VERSION)" -m "Release v$(NEW_VERSION)"
	@echo "Bumped, committed and tagged v$(NEW_VERSION)"

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
	@echo "Creating release PR..."
	gh pr create --base production --head main \
		--title "Release $(DEPLOY_VERSION)" \
		--body "Automated release PR for v$(DEPLOY_VERSION)"

# === Django dev targets ===

dev:
	docker compose -f docker-compose.dev.yml up -d

dev-build:
	docker compose -f docker-compose.dev.yml up -d --build
	@echo ""
	@echo "Dev environment started:"
	@echo "  Web:        http://localhost:8005"
	@echo "  PostgreSQL: localhost:5435"

dev-logs:
	docker compose -f docker-compose.dev.yml logs -f

dev-down:
	docker compose -f docker-compose.dev.yml down

dev-migrate:
	docker compose -f docker-compose.dev.yml exec web python manage.py migrate

dev-shell:
	docker compose -f docker-compose.dev.yml exec web python manage.py shell

dev-import:
	docker compose -f docker-compose.dev.yml exec web python manage.py import_yaml --path /app/devices/ --manifest /app/manifest.yaml

# === Backup ===

backup:
	./scripts/backup-db.sh

# === Help ===

help:
	@echo "Version management targets:"
	@echo "  make version     - Show current version"
	@echo "  make bump-patch  - Bump patch version ($(VERSION) → $(MAJOR).$(MINOR).$$(($(PATCH)+1)))"
	@echo "  make bump-minor  - Bump minor version ($(VERSION) → $(MAJOR).$$(($(MINOR)+1)).0)"
	@echo "  make bump-major  - Bump major version ($(VERSION) → $$(($(MAJOR)+1)).0.0)"
	@echo "  make deploy      - Push and create release PR (HEAD must be tagged)"
	@echo ""
	@echo "Django development targets:"
	@echo "  make dev         - Start local dev environment"
	@echo "  make dev-build   - Start local dev environment (rebuild images)"
	@echo "  make dev-logs    - Follow dev container logs"
	@echo "  make dev-down    - Stop local dev environment"
	@echo "  make dev-migrate - Run database migrations"
	@echo "  make dev-shell   - Open Django shell"
	@echo "  make dev-import  - Import YAML device definitions into database"
	@echo ""
	@echo "Backup targets:"
	@echo "  make backup      - Backup production PostgreSQL database"
