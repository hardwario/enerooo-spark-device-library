.PHONY: help release release-patch release-minor release-major dev dev-build dev-logs dev-down dev-migrate dev-shell dev-import
.DEFAULT_GOAL := help

BUMP ?= patch

# === Library release targets ===

release:
	@if [ -n "$$(git status --porcelain)" ]; then \
		echo "Error: working tree is not clean. Please commit or stash your changes before releasing."; \
		exit 1; \
	fi
	@scripts/bump-version.sh $(BUMP)
	@VERSION=$$(grep -m1 '^version:' manifest.yaml | sed 's/version: *"\(.*\)"/\1/'); \
	git add manifest.yaml && \
	git commit -m "chore(manifest): bump to $$VERSION" && \
	git tag "v$$VERSION" && \
	git push && git push --tags && \
	echo "Released v$$VERSION"

release-patch:
	@$(MAKE) release BUMP=patch

release-minor:
	@$(MAKE) release BUMP=minor

release-major:
	@$(MAKE) release BUMP=major

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

# === Help ===

help:
	@echo "Library release targets:"
	@echo "  release       - Bump patch version, commit, tag, and push (default)"
	@echo "  release-patch - Bump patch version, commit, tag, and push"
	@echo "  release-minor - Bump minor version, commit, tag, and push"
	@echo "  release-major - Bump major version, commit, tag, and push"
	@echo ""
	@echo "Django development targets:"
	@echo "  dev           - Start local dev environment"
	@echo "  dev-build     - Start local dev environment (rebuild images)"
	@echo "  dev-logs      - Follow dev container logs"
	@echo "  dev-down      - Stop local dev environment"
	@echo "  dev-migrate   - Run database migrations"
	@echo "  dev-shell     - Open Django shell"
	@echo "  dev-import    - Import YAML device definitions into database"
