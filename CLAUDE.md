# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A **YAML-based device library** for IoT device definitions used by the ENEROOO Spark platform, plus a Go-based TUI tool (`sparkctl`) for managing the library.

## Repository Structure

- `manifest.yaml` - Central registry of all vendors with version, schema version, and file references
- `devices/*.yaml` - Device definitions organized by vendor (16 vendor files)
- `tools/sparkctl/` - Go TUI application for browsing/editing device definitions

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
```

### Technology-Specific Fields

**Modbus** (`technology_config`):
- `register_definitions[]` - Each with: `field` (name, unit), `scale`, `offset`, `address`, `data_type` (int16, uint16, int32, uint32, float32)

**LoRaWAN** (`technology_config`):
- `device_class` (A/B/C), `downlink_f_port`, plus optional `control_config.capabilities` for relay commands

**wM-Bus** (`technology_config`):
- `manufacturer_code`, `wmbus_device_type` (numeric), `data_record_mapping[]`, `encryption_required`, optional `shared_encryption_key`

## Conventions

- **Conventional commits** with these patterns:
  - `chore(library): add/update [vendor] device types` - device changes
  - `chore(manifest): bump to X.X.X` - version bumps (separate commit)
  - `fix(<vendor>): <description>` - vendor-specific fixes (scope is lowercase vendor name)
  - `feat(tools): <description>` - sparkctl changes
- Keep device entries alphabetically ordered within files when practical
- PR-based workflow: changes go through pull requests, not direct pushes

## sparkctl Tool

**Location:** `tools/sparkctl/`

**Build & Run:**
```bash
cd tools/sparkctl
make deps          # Install dependencies
make build         # Build for current platform (output: build/sparkctl)
make build-all     # Cross-compile for linux/darwin/windows (amd64/arm64)
make run           # Run directly via `go run .`
make clean         # Remove build artifacts
```

**Runtime flags:** `-local` reads from local filesystem instead of GitHub; `-path <dir>` sets the local repo path.

**Architecture:** Built with Bubble Tea (charmbracelet). Key internal packages:
- `internal/tui/` - Main TUI controller (`app.go`, ~1600 lines) with 10 view states (loading, vendor list, device list, device detail/edit, config edit, register list/edit, confirm PR, error)
- `internal/models/` - Data models mapping the YAML device schema to Go structs
- `internal/source/` - `Source` interface with two implementations: `LocalSource` (filesystem) and `GitHubSource` (via `gh` CLI API calls)
- `internal/state/` - Application state: tracks current view, navigation indices, file change tracking (original vs modified)
- `internal/github/` - GitHub client wrapping `gh api` commands for branch creation, file updates, and PR creation
