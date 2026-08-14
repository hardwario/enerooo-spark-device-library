"""Static codec-vs-alarm-mapping lint for LoRaWAN models.

The payload codec is the ground truth for what a device emits: every decoded
field name appears in its JS source. Fields whose names look alarm-ish but
have no alarm mapping are exactly the alarms Spark instances would only ever
surface as generic "unmapped" info alerts — this lint makes the gap visible
at authoring time, on the model detail page, instead of at runtime.
"""

from __future__ import annotations

import re

# Real decoded-output assignments: `<receiver>.field = …` with any receiver
# name — codecs pass the output object around under short names (`d`, `obj`),
# not just `decoded`/`data`. The `(?![=])` keeps comparisons out; object
# literals and envelope keys (data/warnings/errors of the TTN v3 wrapper)
# are deliberately NOT matched — they produced only false positives, and the
# alarm-ish name filter is the real gate anyway.
_ASSIGN_RE = re.compile(
    r"\b[A-Za-z_][A-Za-z0-9_]*\.([A-Za-z_][A-Za-z0-9_]*)\s*=(?![=])"
)

# Bracket-style assignment: x["field"] = … (unused by current codecs, cheap
# to support). Known limitation: output built purely as one object literal
# (`return {data: {status: …}}` with fields inside) is not analyzed — all 26
# current codecs assign field-by-field, keep that convention.
_BRACKET_RE = re.compile(
    r"\b[A-Za-z_][A-Za-z0-9_]*\[[\"']([A-Za-z_][A-Za-z0-9_]*)[\"']\]\s*=(?![=])"
)

_ALARMISH_RE = re.compile(
    r"alarm|error|fault|leak|tamper|status|warn|smoke|fraud|remov|burst"
    r"|frost|backflow|blocked|sabot|intrusion|freeze",
    re.I,
)

# Codec fields that match the alarm-ish pattern but are not device alarms:
# downlink command echoes, configuration readbacks, and reporting-schedule
# parameters (alarm_interval etc.). Counters stay in — a rising counter can
# BE the alarm signal (cf. wM-Bus qsmoke alarm_counter).
_NON_ALARM_RE = re.compile(
    r"^(query_|reset_|release_|confirm_|stop_)"
    r"|(_config|_enable|_counts|_interval|_times|_duration|_date)$",
)


def codec_emitted_fields(script: str) -> set[str]:
    """Field names the codec assigns to its decoded output."""
    script = script or ""
    return set(_ASSIGN_RE.findall(script)) | set(_BRACKET_RE.findall(script))


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
