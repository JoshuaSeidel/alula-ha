# Alula / Cove Security for Home Assistant

[![HACS Validation](https://github.com/joshuaseidel/alula-ha/actions/workflows/validate.yml/badge.svg)](https://github.com/joshuaseidel/alula-ha/actions/workflows/validate.yml)
[![GitHub Release](https://img.shields.io/github/v/release/joshuaseidel/alula-ha)](https://github.com/joshuaseidel/alula-ha/releases)

A Home Assistant custom integration for [Alula](https://alula.com/) / [Cove Security](https://www.covesmart.com/) alarm systems.

## Features

- **Alarm Control Panel** — Arm (Home/Away/Night) and disarm your security system
- **Zone Sensors** — Binary sensors for doors, windows, motion detectors, smoke, and water sensors
- **Trouble Status** — Sensor with detailed trouble flags (AC failure, low battery, communication issues)
- **Last Event** — Tracks the most recent arming/disarming event

## Requirements

- Home Assistant 2026.2 or newer
- Alula / Cove Security account (Cove Connect app credentials)

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Click the three-dot menu and select **Custom repositories**
3. Add `https://github.com/joshuaseidel/alula-ha` with category **Integration**
4. Search for "Alula" and install
5. Restart Home Assistant

### Manual

1. Download the latest release from [GitHub Releases](https://github.com/joshuaseidel/alula-ha/releases)
2. Extract and copy the `custom_components/alula` folder to your Home Assistant `custom_components/` directory
3. Restart Home Assistant

## Configuration

1. Go to **Settings** > **Devices & Services** > **Add Integration**
2. Search for "Alula"
3. Enter your Cove Connect app username and PIN/password

## Entities

| Entity | Type | Description |
|--------|------|-------------|
| Alarm Panel | `alarm_control_panel` | Arm/disarm control with state feedback |
| Zone sensors | `binary_sensor` | One per zone (door, window, motion, smoke, water) |
| Trouble Status | `sensor` | OK/Trouble with detailed attributes |
| Last Event | `sensor` | Last arm/disarm event with timestamps |

## License

[MIT](LICENSE)
