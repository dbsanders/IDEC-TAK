import time


class Deduper:
    def __init__(self, expiry_seconds: int = 60):
        self.expiry_seconds = expiry_seconds
        self._cache: dict[str, tuple[str, float]] = {}

    def _cleanup(self) -> None:
        now = time.monotonic()
        expired = [key for key, (_, expires) in self._cache.items() if expires <= now]
        for key in expired:
            del self._cache[key]

    def make_key(self, source: str, latitude: float, longitude: float, comment: str | None, timestamp: str | None) -> str:
        timestamp_token = timestamp or ""
        comment_token = comment or ""
        return f"{source}|{latitude:.6f}|{longitude:.6f}|{comment_token}|{timestamp_token}"

    def is_duplicate(self, key: str, source_type: str) -> bool:
        self._cleanup()
        existing = self._cache.get(key)
        if existing is None:
            self._cache[key] = (source_type, time.monotonic() + self.expiry_seconds)
            return False

        existing_source, expiry = existing
        if existing_source == "RF" or source_type == "APRS-IS":
            return True

        if source_type == "RF" and existing_source == "APRS-IS":
            self._cache[key] = (source_type, time.monotonic() + self.expiry_seconds)
            return False

        return True
