import pathlib
import yaml

DEFAULT_CONFIG = {
    "aprsis": {
        "enabled": True,
        "server": "noam.aprs2.net",
        "port": 14580,
        "login_call": "N6IPD-15",
        "passcode": "",
        "app_name": "aprs-tak-gw",
        "app_version": "0.1",
    },
    "direwolf": {
        "enabled": True,
        "host": "127.0.0.1",
        "port": 8000,
    },
    "database": {
        "path": "/opt/aprs-tak-gateway/roster.db",
    },
    "gateway": {
        "stale_minutes": 10,
        "roster_poll_seconds": 30,
        "dedupe_seconds": 60,
        "prefer_rf_over_aprsis": True,
    },
    "tak": {
        "enabled": True,
        "host": "tak.local.mesh",
        "port": 8089,
        "protocol": "tls",
        "ca_file": None,
        "cert_file": None,
        "key_file": None,
    },
    "web": {
        "enabled": True,
        "host": "127.0.0.1",
        "port": 8080,
        "admin_password": None,
        "secret_key": None,
    },
}


def load_config(path: str | pathlib.Path) -> dict:
    path = pathlib.Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Configuration file not found: {path}")

    with path.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}

    merged = DEFAULT_CONFIG.copy()
    for key, value in config.items():
        if key in merged and isinstance(value, dict):
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = value

    return merged
