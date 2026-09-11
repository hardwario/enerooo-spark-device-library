"""Model documentation assets: manuals, images, commissioning procedures.

``assets_payload`` is the metadata block consumers get in the published
content, ``devices/<id>/`` and ``models/<key>/assets/``. File URLs are paths
relative to the Library origin (consumers know ``LIBRARY_BASE_URL``) so the
document stays identical between the API and the offline download.

``procedure_to_markdown`` / ``parse_procedure_markdown`` are the on-disk form
of ``ModelProcedure`` used by the YAML export (``procedures/<key>.md``)
and by the assets API.
"""

import re

import yaml
from django.core.exceptions import ObjectDoesNotExist

from .models import ModelProcedure, VendorModel

_FRONT_MATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.DOTALL)


def _api_base(model: VendorModel) -> str:
    return f"/api/v1/models/{model.key}"


def assets_payload(model: VendorModel) -> dict:
    """``{documents: [...], images: [...], procedures: [...]}`` for one model."""
    base = _api_base(model)
    return {
        "documents": [
            {
                "id": str(d.id),
                "title": d.title,
                "size": d.file.size if d.file else 0,
                "url": f"{base}/documents/{d.id}/",
            }
            for d in model.documents.all()
        ],
        "images": [
            {
                "id": str(i.id),
                "url": f"{base}/images/{i.id}/",
                "is_primary": i.is_primary,
                "caption": i.caption,
            }
            for i in model.images.all()
        ],
        "procedure": _procedure_payload(model, base),
    }


def _procedure_payload(model: VendorModel, base: str) -> dict | None:
    try:
        p = model.procedure
    except ObjectDoesNotExist:
        return None
    return {"version": p.version, "title": p.title, "url": f"{base}/procedure/"}


EMPTY_ASSETS: dict = {"documents": [], "images": [], "procedure": None}


def procedure_to_markdown(procedure: ModelProcedure) -> str:
    """Markdown document with YAML front matter (title, model_key, version,
    then the stored extras)."""
    front = {
        "title": procedure.title,
        "model_key": str(procedure.vendor_model.key),
        "version": procedure.version,
    }
    for key, value in (procedure.front_matter or {}).items():
        if key not in front and value not in (None, "", []):
            front[key] = value
    head = yaml.safe_dump(front, sort_keys=False, allow_unicode=True).rstrip("\n")
    return f"---\n{head}\n---\n{procedure.body}"


def parse_procedure_markdown(text: str) -> tuple[dict, str]:
    """Split a procedure ``.md`` into ``(front_matter, body)``. A document
    without front matter yields ``({}, text)``."""
    match = _FRONT_MATTER_RE.match(text)
    if not match:
        return {}, text
    front = yaml.safe_load(match.group(1)) or {}
    if not isinstance(front, dict):
        raise ValueError("Front matter must be a mapping.")
    return front, match.group(2)
