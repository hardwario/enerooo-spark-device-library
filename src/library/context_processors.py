"""Library template context processors."""

from __future__ import annotations

import logging

from .unpublished import unpublished_changes_summary

logger = logging.getLogger(__name__)


def unpublished_changes(request) -> dict:
    """Expose the unpublished-changes summary to every template.

    Fail-soft: never raise out of a context processor — a broken
    summary should not blank out every page in the app. Anonymous
    requests skip the query entirely.
    """
    if not getattr(request.user, "is_authenticated", False):
        return {}
    try:
        summary = unpublished_changes_summary()
    except Exception:  # noqa: BLE001 — see docstring
        logger.exception("unpublished_changes_summary failed")
        return {}
    return {"unpublished_changes": summary.as_template_context()}
