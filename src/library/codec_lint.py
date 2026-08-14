"""Static codec-vs-alarm-mapping lint for LoRaWAN models.

The payload codec is the ground truth for what a device emits: every decoded
field name appears in its JS source. Fields whose names look alarm-ish but
have no alarm mapping are exactly the alarms Spark instances would only ever
surface as generic "unmapped" info alerts — this lint makes the gap visible
at authoring time, on the model detail page, instead of at runtime.
"""

from __future__ import annotations

import re

# Real decoded-output assignments (`decoded.x = …` / `data.x = …`). Object
# literals and envelope keys (data/warnings/errors of the TTN v3 wrapper)
# are deliberately NOT matched — they produced only false positives.
_ASSIGN_RE = re.compile(r"(?:decoded|data)\.([A-Za-z_][A-Za-z0-9_]*)\s*=")

_ALARMISH_RE = re.compile(
    r"alarm|error|fault|leak|tamper|status|warn|smoke|fraud|remov|burst"
    r"|frost|backflow|blocked|sabot|intrusion|freeze",
    re.I,
)

# Codec fields that match the alarm-ish pattern but are not device alarms:
# downlink command echoes and configuration readbacks.
_NON_ALARM_RE = re.compile(
    r"^(query_|reset_|release_|confirm_|stop_)|(_config|_enable|_counts)$",
)


def codec_emitted_fields(script: str) -> set[str]:
    """Field names the codec assigns to its decoded output."""
    return set(_ASSIGN_RE.findall(script or ""))


def unmapped_alarm_fields(script: str, mappings: list[dict]) -> list[str]:
    """Alarm-ish codec output fields that no alarm mapping declares as source.

    Returns a sorted list of field names; empty = fully covered (or nothing
    alarm-ish emitted).
    """
    alarmish = {
        f
        for f in codec_emitted_fields(script)
        if _ALARMISH_RE.search(f) and not _NON_ALARM_RE.search(f)
    }
    mapped_sources = {
        entry.get("source") or "status"
        for entry in (mappings or [])
        if isinstance(entry, dict)
    }
    return sorted(alarmish - mapped_sources)
