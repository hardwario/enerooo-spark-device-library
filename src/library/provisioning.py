"""``VendorModel.provisioning`` — the per-unit input-data schema a model
publishes for Enerooo Provisioning and Spark instance stock.

Shape::

    {
      "input_data": [
        {"key": "dev_eui", "label": {"en": "DevEUI", "cs": "DevEUI"}, "type": "hex",
         "length": 16, "required": true, "secret": false, "scan": true,
         "help": {"en": "Label on the housing"}},
        ...
      ],
      "pairing_key": "dev_eui"
    }

``type`` is one of ``string`` (+``pattern``), ``hex`` / ``digits`` (+``length``),
``int`` (+``min``, ``max``) or ``enum`` (+``choices``). ``pairing_key`` names the
field an instance uses to pair a unit with its device and must be one of the
``input_data`` keys. An empty dict means the model publishes no schema.

Validated in plain Python: the shape is small and the error messages read
better than a JSON Schema trace.
"""

import re

from django.core.exceptions import ValidationError

TYPES = ("string", "hex", "digits", "int", "enum")
KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")
PRODUCT_CODE_RE = r"^[A-Z0-9]{5}$"

# Per-technology starting points for the editor's "Prefill" button.
TEMPLATES: dict[str, dict] = {
    "lorawan": {
        "input_data": [
            {"key": "dev_eui", "label": {"en": "DevEUI", "cs": "DevEUI"}, "type": "hex", "length": 16,
             "required": True, "secret": False, "scan": True},
            {"key": "join_eui", "label": {"en": "JoinEUI", "cs": "JoinEUI"}, "type": "hex", "length": 16,
             "required": True, "secret": False, "scan": False},
            {"key": "app_key", "label": {"en": "AppKey", "cs": "AppKey"}, "type": "hex", "length": 32,
             "required": True, "secret": True, "scan": False},
            {"key": "serial_number", "label": {"en": "Serial number", "cs": "Sériové číslo"}, "type": "string",
             "pattern": "^[A-Z0-9-]{4,32}$", "required": False, "secret": False, "scan": True},
        ],
        "pairing_key": "dev_eui",
    },
    "wmbus": {
        "input_data": [
            {"key": "wmbus_id", "label": {"en": "wM-Bus ID", "cs": "wM-Bus ID"}, "type": "digits", "length": 8,
             "required": True, "secret": False, "scan": True},
            {"key": "wmbus_key", "label": {"en": "wM-Bus AES key", "cs": "wM-Bus AES klíč"}, "type": "hex",
             "length": 32, "required": True, "secret": True, "scan": True},
            {"key": "serial_number", "label": {"en": "Serial number", "cs": "Sériové číslo"}, "type": "string",
             "pattern": "^[A-Z0-9-]{4,32}$", "required": False, "secret": False, "scan": True},
        ],
        "pairing_key": "wmbus_id",
    },
    "modbus": {
        "input_data": [
            {"key": "serial_number", "label": {"en": "Serial number", "cs": "Sériové číslo"}, "type": "string",
             "pattern": "^[A-Z0-9-]{4,32}$", "required": True, "secret": False, "scan": True},
            {"key": "modbus_address", "label": {"en": "Modbus address", "cs": "Modbus adresa"}, "type": "int",
             "min": 1, "max": 247, "required": True, "secret": False, "scan": False},
        ],
        "pairing_key": "serial_number",
    },
}


def _err(msg: str) -> ValidationError:
    return ValidationError({"provisioning": msg})


def _check_label(field: dict, name: str, idx: int, required: bool) -> None:
    value = field.get(name)
    if value is None:
        if required:
            raise _err(f"Field #{idx}: ``{name}`` is required.")
        return
    if not isinstance(value, dict) or not value:
        raise _err(f"Field #{idx}: ``{name}`` must be a non-empty object of language → text.")
    for lang, text in value.items():
        if not isinstance(lang, str) or not isinstance(text, str) or not text.strip():
            raise _err(f"Field #{idx}: ``{name}`` entries must map a language code to non-empty text.")
    if required and not value.get("en"):
        raise _err(f"Field #{idx}: ``{name}`` needs an ``en`` entry.")


def _check_int(field: dict, name: str, idx: int, *, positive: bool = False) -> int | None:
    value = field.get(name)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise _err(f"Field #{idx}: ``{name}`` must be an integer.")
    if positive and value <= 0:
        raise _err(f"Field #{idx}: ``{name}`` must be positive.")
    return value


def validate_provisioning(value) -> None:
    """Raise ``ValidationError`` unless ``value`` is a valid provisioning schema."""
    if value in (None, {}):
        return
    if not isinstance(value, dict):
        raise _err("Must be an object with ``input_data`` and ``pairing_key``.")
    unknown = set(value) - {"input_data", "pairing_key"}
    if unknown:
        raise _err(f"Unknown keys: {', '.join(sorted(unknown))}.")

    fields = value.get("input_data")
    if not isinstance(fields, list):
        raise _err("``input_data`` must be a list.")

    seen: set[str] = set()
    for idx, field in enumerate(fields):
        if not isinstance(field, dict):
            raise _err(f"Field #{idx} must be an object.")
        key = field.get("key")
        if not isinstance(key, str) or not KEY_RE.match(key):
            raise _err(f"Field #{idx}: ``key`` must match {KEY_RE.pattern}.")
        if key in seen:
            raise _err(f"Duplicate field key ``{key}``.")
        seen.add(key)

        _check_label(field, "label", idx, required=True)
        _check_label(field, "help", idx, required=False)

        ftype = field.get("type")
        if ftype not in TYPES:
            raise _err(f"Field ``{key}``: ``type`` must be one of {', '.join(TYPES)}.")
        for flag in ("required", "secret", "scan"):
            if flag in field and not isinstance(field[flag], bool):
                raise _err(f"Field ``{key}``: ``{flag}`` must be true or false.")

        if ftype in ("hex", "digits"):
            if _check_int(field, "length", idx, positive=True) is None:
                raise _err(f"Field ``{key}``: ``{ftype}`` needs a positive ``length``.")
        elif ftype == "int":
            lo = _check_int(field, "min", idx)
            hi = _check_int(field, "max", idx)
            if lo is not None and hi is not None and lo > hi:
                raise _err(f"Field ``{key}``: ``min`` must not exceed ``max``.")
        elif ftype == "string":
            pattern = field.get("pattern")
            if pattern is not None:
                if not isinstance(pattern, str):
                    raise _err(f"Field ``{key}``: ``pattern`` must be a string.")
                try:
                    re.compile(pattern)
                except re.error as exc:
                    raise _err(f"Field ``{key}``: invalid ``pattern`` ({exc}).") from exc
        elif ftype == "enum":
            choices = field.get("choices")
            if not isinstance(choices, list) or not choices or not all(
                isinstance(c, str) and c for c in choices
            ):
                raise _err(f"Field ``{key}``: ``enum`` needs a non-empty list of string ``choices``.")

    pairing_key = value.get("pairing_key")
    if fields:
        if pairing_key not in seen:
            raise _err("``pairing_key`` must name one of the ``input_data`` keys.")
    elif pairing_key:
        raise _err("``pairing_key`` set but ``input_data`` is empty.")
