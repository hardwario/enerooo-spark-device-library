.PHONY: help release release-patch release-minor release-major
.DEFAULT_GOAL := help

BUMP ?= patch

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

help:
	@echo "Available targets:"
	@echo "  release       - Bump patch version, commit, tag, and push (default)"
	@echo "  release-patch - Bump patch version, commit, tag, and push"
	@echo "  release-minor - Bump minor version, commit, tag, and push"
	@echo "  release-major - Bump major version, commit, tag, and push"
