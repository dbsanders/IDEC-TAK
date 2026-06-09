# APRS-to-TAK Gateway

This project implements a gateway that receives APRS position data from local RF APRS via Dire Wolf AGW and APRS-IS, filters known users from an SQLite roster, converts position packets to Cursor-on-Target (CoT), and forwards them to a TAK server.

## Features

- APRS-IS listener with generated filter based on enabled roster entries
- Dire Wolf AGW listener for local RF APRS packets
- SQLite roster database with tactical call mapping and match_all_ssids support
- APRS position packet parsing for `!`, `=`, `/`, and `@` packet types
- CoT XML generation and TAK TCP/TLS forwarding
- Web UI for roster management using FastAPI
- In-memory duplicate suppression with RF preference

## Installation

```bash
python -m pip install -e .
```

## Configuration

Copy `config.yaml.example` to `config.yaml` and edit values.

## Running

Gateway service:

```bash
python -m aprs_tak_gateway.main --config config.yaml
```

Web UI:

```bash
uvicorn aprs_tak_gateway.web:app --host 127.0.0.1 --port 8080
```

## Python Files

Runtime package:

- `aprs_tak_gateway/__init__.py` - Package metadata, including the project version.
- `aprs_tak_gateway/main.py` - Command-line entry point that loads configuration, starts enabled APRS listeners, and forwards parsed packets to TAK.
- `aprs_tak_gateway/config.py` - Loads `config.yaml` and merges it with default configuration values.
- `aprs_tak_gateway/aprsis.py` - Connects to APRS-IS, applies the roster-generated filter, parses incoming packets, and forwards matched positions.
- `aprs_tak_gateway/direwolf_agw.py` - Connects to a local Dire Wolf AGW feed, converts AGW lines into APRS packets, and forwards matched RF positions.
- `aprs_tak_gateway/aprs_parser.py` - Parses APRS position packets into normalized coordinates, altitude, course, speed, timestamp, and comment fields.
- `aprs_tak_gateway/cot.py` - Builds Cursor-on-Target XML events from parsed APRS positions and roster display information.
- `aprs_tak_gateway/dedupe.py` - Suppresses repeated position reports for a configurable time window, preferring RF reports over APRS-IS duplicates.
- `aprs_tak_gateway/roster.py` - Manages the SQLite roster database, schema migrations, callsign matching, settings, and APRS-IS filter generation.
- `aprs_tak_gateway/tak_client.py` - Sends CoT XML events to a TAK server over TCP or TLS.
- `aprs_tak_gateway/web.py` - Provides the FastAPI web UI for login, roster management, settings, and APRS-IS reload requests.

Tests:

- `tests/test_aprs_parser.py` - Verifies APRS position parsing, including timestamps and RF/APRS-IS source labels.
- `tests/test_cot.py` - Verifies CoT XML generation includes expected identifiers, coordinates, display names, comments, and original APRS data.
- `tests/test_filter_generation.py` - Verifies roster entries produce the expected APRS-IS filter text.
- `tests/test_roster.py` - Verifies roster callsign matching, case-insensitive lookups, and schema migration behavior.
- `tests/test_web.py` - Verifies web login creates a signed session cookie accepted by authenticated routes.

## Database

The gateway uses SQLite for roster and settings storage. The database file path is configured in `config.yaml`.

## Systemd

Sample service unit files are included in `systemd/`.
