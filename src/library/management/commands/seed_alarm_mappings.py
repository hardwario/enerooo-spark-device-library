"""Seed AlarmConfig.mappings for wM-Bus models.

Combines two sources per driver:

1. Status flag strings extracted from a wmbusmeters checkout
   (``--wmbusmeters PATH``) — ``drivers/src/*.xmq`` lookup tables and
   ``src/driver_*.cc`` ``Translate::Map`` entries.
2. Curated severities/descriptions in ``library/data/wmbus_alarm_severities.json``
   (exported from Spark's built-in driver alarm registry). Flags without a
   curated entry default to severity ``warning``.

The driver for a model is read from ``wmbus_config.wmbusmeters_driver``, with
``library/data/wmbus_model_drivers.json`` as fallback for models where the
driver field is empty (matching the Spark wM-Bus reference doc).

Models whose AlarmConfig.mappings are already non-empty are skipped unless
``--force``. Changes are recorded in DeviceHistory so the next published
LibraryVersion picks them up.
"""

import json
import re
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from library.history import record_history, snapshot_device
from library.models import AlarmConfig, DeviceHistory, VendorModel

DATA_DIR = Path(__file__).resolve().parents[2] / "data"

_XMQ_DRIVER_RE = re.compile(r"driver\s*\{\s*name\s*=\s*(\w+)")
_XMQ_MAP_RE = re.compile(r"\bmap\s*\{\s*name\s*=\s*([A-Za-z0-9_]+)")
_CC_NAME_RE = re.compile(r'di\.setName\("([^"]+)"\)')
_CC_MAP_RE = re.compile(r'Translate::Map\(\s*0x[0-9a-fA-F]+\s*,\s*"([^"]+)"')


def _parse_xmq(path: Path) -> tuple[str, dict[str, set[str]]] | None:
    """Return (driver_name, {source_field: flags}) for one .xmq driver file."""
    text = path.read_text(errors="replace")
    m = _XMQ_DRIVER_RE.search(text)
    if not m:
        return None
    driver = m.group(1)

    sources: dict[str, set[str]] = {}
    # Walk ``field {`` blocks with brace counting; a lookup's maps belong to
    # the enclosing field. Fields injected into the joined wmbusmeters
    # ``status`` output (STATUS / INJECT_INTO_STATUS / INCLUDE_TPL_STATUS
    # attributes) publish under source "status", others under the field name.
    for fm in re.finditer(r"\bfield\s*\{", text):
        depth, i = 1, fm.end()
        while i < len(text) and depth:
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
            i += 1
        block = text[fm.end() : i]
        flags = set(_XMQ_MAP_RE.findall(block))
        if not flags:
            continue
        name_m = re.search(r"name\s*=\s*(\S+)", block)
        field_name = name_m.group(1) if name_m else "status"
        attrs_m = re.search(r"attributes\s*=\s*(\S+)", block)
        attrs = attrs_m.group(1) if attrs_m else ""
        source = "status" if ("STATUS" in attrs or field_name == "status") else field_name
        sources.setdefault(source, set()).update(flags)
    return driver, sources


def _parse_cc(path: Path) -> tuple[str, dict[str, set[str]]] | None:
    """Return (driver_name, {"status": flags}) for one C++ driver file."""
    text = path.read_text(errors="replace")
    m = _CC_NAME_RE.search(text)
    if not m:
        return None
    flags = set(_CC_MAP_RE.findall(text))
    if not flags:
        return m.group(1), {}
    # ponytail: C++ lookups are attributed to "status" wholesale; per-field
    # source detection only if a real driver proves to need it.
    return m.group(1), {"status": flags}


def extract_driver_flags(wmbusmeters_path: Path) -> dict[str, dict[str, set[str]]]:
    """Parse a wmbusmeters checkout → {driver: {source: flags}}."""
    result: dict[str, dict[str, set[str]]] = {}
    for xmq in sorted((wmbusmeters_path / "drivers" / "src").glob("*.xmq")):
        parsed = _parse_xmq(xmq)
        if parsed:
            driver, sources = parsed
            for src, flags in sources.items():
                result.setdefault(driver, {}).setdefault(src, set()).update(flags)
    for cc in sorted((wmbusmeters_path / "src").glob("driver_*.cc")):
        parsed = _parse_cc(cc)
        if parsed:
            driver, sources = parsed
            for src, flags in sources.items():
                result.setdefault(driver, {}).setdefault(src, set()).update(flags)
    return result


class Command(BaseCommand):
    help = "Seed AlarmConfig.mappings for wM-Bus models from wmbusmeters drivers + curated severities."

    def add_arguments(self, parser):
        parser.add_argument(
            "--wmbusmeters",
            help="Path to a wmbusmeters checkout to extract driver status flags from. "
            "Omit to seed from the curated severities file only.",
        )
        parser.add_argument("--dry-run", action="store_true", help="Report without writing.")
        parser.add_argument(
            "--force",
            action="store_true",
            help="Overwrite models whose AlarmConfig.mappings are already non-empty.",
        )

    def handle(self, *args, **options):
        overlay = json.loads((DATA_DIR / "wmbus_alarm_severities.json").read_text())
        model_drivers = {
            (e["vendor"].lower(), e["model_number"].lower()): e["driver"]
            for e in json.loads((DATA_DIR / "wmbus_model_drivers.json").read_text())
        }

        extracted: dict[str, dict[str, set[str]]] = {}
        if options["wmbusmeters"]:
            root = Path(options["wmbusmeters"]).expanduser()
            if not (root / "src").is_dir():
                raise CommandError(f"{root} does not look like a wmbusmeters checkout")
            extracted = extract_driver_flags(root)
            self.stdout.write(
                f"Extracted flags for {len(extracted)} drivers from {root}"
            )

        stats = {"seeded": 0, "skipped_existing": 0, "no_driver": 0, "no_flags": 0}

        models = VendorModel.objects.filter(technology="wmbus").select_related(
            "vendor", "wmbus_config"
        )
        for model in models:
            driver = (
                getattr(getattr(model, "wmbus_config", None), "wmbusmeters_driver", "")
                or model_drivers.get(
                    (model.vendor.name.lower(), model.model_number.lower()), ""
                )
            )
            if driver in ("", "auto"):
                stats["no_driver"] += 1
                self.stdout.write(f"  - {model}: no driver known, skipped")
                continue

            entries = self._build_entries(
                extracted.get(driver, {}), overlay.get(driver, {})
            )
            if not entries:
                stats["no_flags"] += 1
                self.stdout.write(f"  - {model}: driver '{driver}' has no known flags")
                continue

            ac, _ = AlarmConfig.objects.get_or_create(device_type=model)
            if ac.mappings and not options["force"]:
                stats["skipped_existing"] += 1
                self.stdout.write(
                    f"  - {model}: alarm mappings already set "
                    f"({len(ac.mappings)} entries), skipped (use --force)"
                )
                continue

            stats["seeded"] += 1
            self.stdout.write(
                self.style.SUCCESS(
                    f"  + {model}: driver '{driver}' -> {len(entries)} alarm mappings"
                )
            )
            if options["dry_run"]:
                continue

            old_snapshot = snapshot_device(model)
            ac.mappings = entries
            ac.save()
            record_history(
                model,
                DeviceHistory.Action.UPDATED,
                user=None,
                previous_snapshot=old_snapshot,
            )

        prefix = "[dry-run] " if options["dry_run"] else ""
        self.stdout.write(
            f"{prefix}seeded={stats['seeded']} skipped_existing={stats['skipped_existing']} "
            f"no_driver={stats['no_driver']} no_flags={stats['no_flags']}"
        )

    @staticmethod
    def _build_entries(
        extracted_sources: dict[str, set[str]], overlay_entry: dict
    ) -> list[dict]:
        curated = overlay_entry.get("flags", {})
        curated_source = overlay_entry.get("source", "status")

        by_flag: dict[tuple[str, str], dict] = {}
        for source, flags in extracted_sources.items():
            for flag in flags:
                sev, desc = curated.get(flag) or (
                    "warning",
                    flag.replace("_", " ").capitalize(),
                )
                by_flag[(source, flag)] = {
                    "source": source,
                    "match": flag,
                    "severity": sev,
                    "description": desc,
                }
        # Curated flags the extraction didn't find (fork drift, C++ parse
        # misses) still get seeded under the overlay's source field.
        for flag, (sev, desc) in curated.items():
            if not any(f == flag for _, f in by_flag):
                by_flag[(curated_source, flag)] = {
                    "source": curated_source,
                    "match": flag,
                    "severity": sev,
                    "description": desc,
                }
        return sorted(by_flag.values(), key=lambda e: (e["source"], e["match"]))
