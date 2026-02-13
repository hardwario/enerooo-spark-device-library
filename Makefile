.PHONY: release release-minor release-major

BUMP ?= patch

release:
	@scripts/bump-version.sh $(BUMP)
	@VERSION=$$(grep -m1 '^version:' manifest.yaml | sed 's/version: *"\(.*\)"/\1/'); \
	git add manifest.yaml && \
	git commit -m "chore(manifest): bump to $$VERSION" && \
	git tag "v$$VERSION" && \
	git push && git push --tags && \
	echo "Released v$$VERSION"

release-minor:
	@$(MAKE) release BUMP=minor

release-major:
	@$(MAKE) release BUMP=major
