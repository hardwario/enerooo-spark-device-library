# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A **device library** for IoT device definitions used by the ENEROOO Spark platform, with a Django web application for managing the library. The database is the source of truth; YAML export is available for backup/sync.

## Repository Structure

- `src/` - Django web application for library management

## Device Schema (v2)

Each device definition follows this structure:

```yaml
device_types:
- vendor_name: string
  model_number: string
  name: string
  device_type: power_meter | gateway | environment_sensor | water_meter | heat_meter
  description: string (optional)
  technology_config:
    technology: modbus | lorawan | wmbus
    # technology-specific fields below
  control_config: # optional
    capabilities: {}
    controllable: boolean
  processor_config: # optional
    decoder_type: string
  product_code: string (optional) # ENEROOO ER code, 5 chars, unique per model; Enerooo ID prefix
  provisioning: # optional, per-unit input-data schema for Enerooo Provisioning (see src/library/provisioning.py)
    input_data: [{key, label, type: string|hex|digits|int, required, secret, scan, length|min,max|pattern}]
    pairing_key: string # one of input_data keys
```

### Technology-Specific Fields

**Modbus** (`technology_config`):
- `register_definitions[]` - Each with: `field` (name, unit), `scale`, `offset`, `address`, `data_type` (int16, uint16, int32, uint32, float32)

**LoRaWAN** (`technology_config`):
- `device_class` (A/B/C), `downlink_f_port`, plus optional `control_config.capabilities` for relay commands

**wM-Bus** (`technology_config`):
- `manufacturer_code`, `wmbus_version` (hex byte, e.g. "1b"), `wmbus_device_type` (numeric), `data_record_mapping[]`, `encryption_required`, optional `shared_encryption_key`

## Conventions

- **Conventional commits** with these patterns:
  - `chore(library): add/update [vendor] device types` - device changes
  - `chore(manifest): bump to X.X.X` - version bumps (separate commit)
  - `fix(<vendor>): <description>` - vendor-specific fixes (scope is lowercase vendor name)
  - `feat(tools): <description>` - web application changes
- Keep device entries alphabetically ordered within files when practical
- PR-based workflow: changes go through pull requests, not direct pushes

## Web UI Conventions

Pages are being redesigned one at a time; `src/library/templates/library/devicetype_detail.html` is the reference for updated pages.

- **Tailwind** is v3 from the Play CDN (`src/templates/base.html`), so there is no build step: arbitrary values (`grid-cols-[...]`) and the `container-queries` plugin work directly.
- **Size layouts by the content area, not the viewport.** From `md` up, the app nav takes 224px, so viewport breakpoints don't match the space a page actually has. An updated page opts in with `{% block main_container %}@container{% endblock %}` and uses `@2xl:` / `@5xl:` for layout changes (columns, card grids, header row vs. stacked). `sm:` is fine for small cosmetic tweaks such as padding.
- **Don't put `@container` on `<main>` globally** until every page has opted in. A size container stops `<main>` from growing with wide tables, which breaks list pages that haven't been updated yet.
- **Detail page layout:** key facts go in the page header rather than a "General" card. Wide content (tables, code) goes in the main column, and compact key/value cards go in a fixed-width sidebar. Missing config sections share a single "Not configured yet" card instead of an empty card each.
- Tables sit inside cards and scroll horizontally (`overflow-x-auto`) instead of overflowing the page.
- Icon-only buttons need an `aria-label` (or screen-reader-only text when the visible label changes, e.g. Add/Edit).
- Check responsive changes at roughly 390, 800, 1100 and 1300px viewport widths.

