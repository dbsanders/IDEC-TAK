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

## Database

The gateway uses SQLite for roster and settings storage. The database file path is configured in `config.yaml`.

## Systemd

Sample service unit files are included in `systemd/`.
