# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a **YAML-based device library** for IoT device definitions used by the ENEROOO Spark platform. It contains no executable code—only declarative device configuration files.

## Repository Structure

- `manifest.yaml` - Central registry of all vendors with version, schema version, and file references
- `devices/*.yaml` - Device definitions organized by vendor (16 vendor files)

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
    # technology-specific configuration
  control_config: # optional
    capabilities: {}
    controllable: boolean
  processor_config: # optional
    decoder_type: string
```

## Supported Technologies

**Modbus** - Register-based communication for power meters
- Uses `register_definitions` with field mappings, data types (int16, uint16, int32, uint32), scale/offset

**LoRaWAN** - Long-range wireless for sensors and smart plugs
- Includes device_class, downlink_fport, decoder_type
- Control commands via f_port configuration

**wM-Bus** - Wireless M-Bus for utility meters
- Requires manufacturer_code, wmbus_device_type, data_records mapping
- May include encryption requirements

## Workflow

When adding or modifying devices:
1. Edit the appropriate vendor file in `devices/`
2. Follow the existing schema patterns within that file
3. Update `manifest.yaml` version when making releases

## Conventions

- Use conventional commits: `chore(library): update [vendor] device types`
- Bump manifest version on releases: `chore(manifest): bump to X.X.X`
- Keep device entries alphabetically ordered within files when practical

## sparkctl Tool

A TUI application for browsing and editing device definitions remotely via GitHub.

**Location:** `tools/sparkctl/`

**Requirements:**
- Go 1.21+
- GitHub CLI (`gh`) authenticated

**Build Commands:**
```bash
cd tools/sparkctl
make deps          # Install dependencies
make build         # Build for current platform
make build-all     # Build for Linux, Windows, macOS (amd64/arm64)
make run           # Run directly without building
```

**Features:**
- Browse vendors and devices from GitHub
- Inline field-by-field editing
- Creates PRs for changes (does not push directly)
