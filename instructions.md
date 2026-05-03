## Project: APRS-to-TAK Gateway

Build a Python service that receives APRS position data from both:

1. **Local RF APRS via Dire Wolf AGW port**
2. **APRS-IS via Internet**

Then it filters known users, applies optional tactical callsign mappings, converts positions to **Cursor-on-Target XML**, and sends them to a TAK server.

Dire Wolf supports acting as a software TNC/APRS decoder and exposes decoded packets to client applications over AGW/KISS network interfaces. APRS-IS supports server-side filters on port 14580, with filter commands beginning with `filter`. ([Debian Manpages][1])

---

## High-level architecture

```text
                      ┌──────────────────┐
RF APRS ─ Dire Wolf ─▶│                  │
          AGW :8000   │                  │
                      │ APRS-to-TAK       │── CoT XML/TLS ─▶ TAK Server
APRS-IS :14580 ──────▶│ Gateway           │
                      │                  │
SQLite roster DB ────▶│                  │
                      └──────────────────┘
```

The gateway should run as a long-running Linux service, probably under `systemd`, on a Raspberry Pi 4 or similar.

---

## Main requirements

### 1. APRS-IS listener

Connect to APRS-IS using:

```text
Server: noam.aprs2.net
Port: 14580
```

Login format:

```text
user N6IPD-15 pass <passcode> vers aprs-tak-gw 0.1 filter <generated_filter>
```

The filter should be generated from the enabled roster entries. Example:

```text
filter b/K6ABC*/N6XYZ-7/W6DEF*
```

The APRS-IS filter is only for reducing traffic. The local database check is still the real authorization/control layer.

When the roster changes, the APRS-IS connection should reconnect with a newly generated filter. A simple approach is to poll a roster version or `updated_at` timestamp every 30–60 seconds.

---

### 2. Dire Wolf AGW listener

Connect to Dire Wolf locally:

```text
Host: 127.0.0.1
Port: 8000
```

Dire Wolf config should include:

```text
AGWPORT 8000
```

The AGW listener should receive decoded RF APRS packets from Dire Wolf.

Current test output from the prototype looks like this:

```text
[AGW kind=K from=N6ZAR-2 to=APAT81 len=81]
!3409.94N/11809.49Wk183/018/A=000853Hi, have a great day![15:02:17]
```

The gateway can reconstruct this internally as:

```text
N6ZAR-2>APAT81:!3409.94N/11809.49Wk183/018/A=000853Hi, have a great day!
```

---

### 3. APRS parsing

Initially support station position packets only:

```text
!  position without timestamp
=  position without timestamp + messaging
/  position with timestamp
@  position with timestamp + messaging
```

Ignore these initially:

```text
;  APRS object
)  APRS item
T  telemetry
:  message
```

Later enhancement: optionally support APRS objects/items if needed.

Extract at minimum:

```text
source_callsign
destination
latitude
longitude
symbol table / symbol
course/speed if present
altitude if present
comment
timestamp if present
source type: RF or APRS-IS
```

A good Python library may help with APRS parsing, but the first version can implement only position parsing if simpler.

---

### 4. Roster database

Use SQLite, not MariaDB initially.

SQLite is sufficient because this is mostly a local lookup table with occasional web UI edits. It avoids a database daemon, users/passwords, extra RAM, TCP listener security, backup complexity, and service ordering issues.

Suggested database file:

```text
/opt/aprs-tak-gateway/roster.db
```

Suggested schema:

```sql
CREATE TABLE roster (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    aprs_call TEXT NOT NULL UNIQUE,
    enabled INTEGER NOT NULL DEFAULT 1,

    -- If true, K6ABC matches K6ABC, K6ABC-7, K6ABC-9, etc.
    match_all_ssids INTEGER NOT NULL DEFAULT 1,

    -- Stable TAK identity. Do not use tactical call as UID.
    tak_uid TEXT NOT NULL UNIQUE,

    -- Default display name if no tactical call is assigned.
    tak_display_name TEXT NOT NULL,

    -- Optional current tactical display name.
    tactical_call TEXT,

    team TEXT,
    role TEXT,
    icon TEXT,
    remarks TEXT,

    last_heard_at TEXT,
    last_heard_source TEXT,

    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
```

Lookup logic:

```text
1. Exact match first: K6ABC-7
2. If not found, fallback to base callsign: K6ABC, only if match_all_ssids = 1
3. If no enabled match, drop packet
4. If tactical_call exists, use it as TAK display name
5. Otherwise use tak_display_name
6. Always preserve original APRS callsign in CoT detail metadata
```

---

### 5. Web UI

Build a simple local web UI, probably Flask or FastAPI.

Required pages/features:

```text
Login page
Roster list
Add user
Edit user
Enable/disable user
Delete user or mark inactive
Assign/remove tactical callsign
Set match_all_ssids true/false
View last heard time/source
View generated APRS-IS filter
Manual reconnect/reload button
```

This web UI can run on the Pi and edit the same SQLite DB used by the gateway.

Basic security:

```text
Bind to localhost by default, or LAN IP only if needed
Simple username/password login
Store password hash, not plaintext
Optional: use nginx reverse proxy later
```

---

### 6. TAK / CoT output

Generate Cursor-on-Target XML and send it to the TAK server.

TAK destination should be configurable:

```yaml
tak:
  host: tak.example.local
  port: 8089
  protocol: tls
  cert_file: /opt/aprs-tak-gateway/certs/client.pem
  key_file: /opt/aprs-tak-gateway/certs/client.key
  ca_file: /opt/aprs-tak-gateway/certs/ca.pem
```

CoT event should use a stable UID:

```text
uid = aprs.<original_aprs_callsign>
```

Example:

```text
aprs.K6ABC-7
```

Do **not** use the tactical callsign as the UID because tactical assignments may change.

Display name should be:

```text
tactical_call if set
else tak_display_name
else original APRS callsign
```

CoT should include a stale time. Suggested default:

```text
stale = now + 10 minutes
```

---

### 7. Deduplication

Because the same RF packet may arrive from both Dire Wolf and APRS-IS, add an in-memory duplicate cache.

Example key:

```text
source_callsign + latitude + longitude + comment + rounded_timestamp
```

Or:

```text
source_callsign + raw_payload
```

Cache duration:

```text
30–90 seconds
```

Preference:

```text
If duplicate exists, prefer RF over APRS-IS.
```

This prevents duplicate TAK updates.

---

### 8. Logging

Log important events, but do not write every packet forever.

Suggested logs:

```text
INFO: connected to APRS-IS
INFO: connected to Dire Wolf AGW
INFO: roster changed, reconnecting APRS-IS with new filter
INFO: sent K6ABC-7 as RACES-12 via RF
INFO: ignored W1XYZ-9, not in roster
WARNING: failed to parse packet
ERROR: TAK connection failed, retrying
```

Avoid excessive SD card writes on Raspberry Pi. Use journald and log rotation.

---

### 9. Configuration file

Use a YAML config, for example:

```yaml
aprsis:
  enabled: true
  server: noam.aprs2.net
  port: 14580
  login_call: N6IPD-15
  passcode: "12420"
  app_name: aprs-tak-gw
  app_version: "0.1"

direwolf:
  enabled: true
  host: 127.0.0.1
  port: 8000

database:
  path: /opt/aprs-tak-gateway/roster.db

gateway:
  stale_minutes: 10
  roster_poll_seconds: 30
  dedupe_seconds: 60
  prefer_rf_over_aprsis: true

tak:
  enabled: true
  host: tak.local.mesh
  port: 8089
  protocol: tls
  ca_file: /opt/aprs-tak-gateway/certs/ca.pem
  cert_file: /opt/aprs-tak-gateway/certs/client.pem
  key_file: /opt/aprs-tak-gateway/certs/client.key

web:
  enabled: true
  host: 127.0.0.1
  port: 8080
```

---

## Suggested Python project structure

```text
aprs-tak-gateway/
├── README.md
├── pyproject.toml
├── config.yaml.example
├── systemd/
│   ├── aprs-tak-gateway.service
│   └── aprs-tak-web.service
├── aprs_tak_gateway/
│   ├── __init__.py
│   ├── main.py
│   ├── config.py
│   ├── aprsis.py
│   ├── direwolf_agw.py
│   ├── aprs_parser.py
│   ├── roster.py
│   ├── cot.py
│   ├── tak_client.py
│   ├── dedupe.py
│   └── web.py
└── tests/
    ├── test_aprs_parser.py
    ├── test_roster.py
    ├── test_filter_generation.py
    └── test_cot.py
```

---

## Implementation milestones

### Milestone 1: RF receive test

Create `direwolf_agw.py` that connects to AGW port 8000 and prints packets like:

```text
N6ZAR-2>APAT81:!3409.94N/11809.49Wk183/018/A=000853Hi, have a great day!
```

### Milestone 2: APRS-IS receive test

Create `aprsis.py` that connects to APRS-IS, logs in, applies a filter, and prints received APRS lines.

### Milestone 3: SQLite roster

Create DB schema, lookup functions, and APRS-IS filter generation from enabled users.

### Milestone 4: APRS parser

Parse station position packets and extract lat/lon.

### Milestone 5: CoT generator

Generate TAK-compatible CoT XML from parsed APRS position and roster mapping.

### Milestone 6: TAK sender

Send CoT XML to TAK server over configured TCP/TLS endpoint.

PyTAK may be useful here because it provides Python classes/functions for TAK clients, Cursor-on-Target events, and CoT serialization. ([PyPI][2])

### Milestone 7: Web UI

Add Flask/FastAPI web UI for roster/tactical callsign management.

### Milestone 8: systemd deployment

Run gateway and web UI as services with auto-restart.

---

## Important design rules

```text
Unknown callsigns are dropped.
APRS-IS filters reduce traffic but are not trusted for authorization.
Roster DB is the source of truth.
TAK UID must be stable.
Tactical callsign is display-only and may change.
Original FCC/APRS callsign must be preserved in CoT detail.
RF source should be preferred over APRS-IS for duplicate packets.
APRS-IS listener should reconnect when roster/filter changes.
```


