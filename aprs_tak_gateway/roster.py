import asyncio
import aiosqlite
from dataclasses import dataclass
from typing import Any


@dataclass
class RosterEntry:
    id: int
    aprs_call: str
    enabled: bool
    match_all_ssids: bool
    tak_uid: str
    tak_display_name: str
    tactical_call: str | None
    team: str | None
    role: str | None
    icon: str | None
    remarks: str | None
    last_heard_at: str | None
    last_heard_source: str | None
    created_at: str | None
    updated_at: str | None

    @property
    def display_name(self) -> str:
        if self.tactical_call:
            return self.tactical_call
        if self.tak_display_name:
            return self.tak_display_name
        return self.aprs_call

    @property
    def base_call(self) -> str:
        if "-" in self.aprs_call:
            return self.aprs_call.split("-", 1)[0]
        return self.aprs_call


class RosterDB:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._lock = asyncio.Lock()
        self._connection: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        self._connection = await aiosqlite.connect(self.db_path)
        self._connection.row_factory = aiosqlite.Row
        await self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS roster (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                aprs_call TEXT NOT NULL UNIQUE,
                enabled INTEGER NOT NULL DEFAULT 1,
                match_all_ssids INTEGER NOT NULL DEFAULT 1,
                tak_uid TEXT NOT NULL UNIQUE,
                tak_display_name TEXT NOT NULL,
                tactical_call TEXT,
                team TEXT,
                role TEXT,
                icon TEXT,
                remarks TEXT,
                last_heard_at TEXT,
                last_heard_source TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        await self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        await self._connection.commit()

    async def close(self) -> None:
        if self._connection:
            await self._connection.close()
            self._connection = None

    async def _execute(self, sql: str, params: tuple[Any, ...] = ()) -> aiosqlite.Cursor:
        if self._connection is None:
            raise RuntimeError("Database not initialized")
        return await self._connection.execute(sql, params)

    async def _fetchall(self, sql: str, params: tuple[Any, ...] = ()) -> list[aiosqlite.Row]:
        cursor = await self._execute(sql, params)
        return await cursor.fetchall()

    async def _fetchone(self, sql: str, params: tuple[Any, ...] = ()) -> aiosqlite.Row | None:
        cursor = await self._execute(sql, params)
        return await cursor.fetchone()

    async def get_enabled_entries(self) -> list[RosterEntry]:
        rows = await self._fetchall(
            "SELECT * FROM roster WHERE enabled = 1 ORDER BY aprs_call"
        )
        return [self._row_to_entry(row) for row in rows]

    async def get_all_entries(self) -> list[RosterEntry]:
        rows = await self._fetchall("SELECT * FROM roster ORDER BY aprs_call")
        return [self._row_to_entry(row) for row in rows]

    async def find_entry_for_aprs_call(self, aprs_call: str) -> RosterEntry | None:
        normalized = self._normalize_call(aprs_call)
        exact = await self._fetchone(
            "SELECT * FROM roster WHERE enabled = 1 AND aprs_call = ?",
            (normalized,),
        )
        if exact:
            return self._row_to_entry(exact)

        base = self._base_call(normalized)
        if base == normalized:
            return None

        row = await self._fetchone(
            "SELECT * FROM roster WHERE enabled = 1 AND match_all_ssids = 1 AND aprs_call = ?",
            (base,),
        )
        return self._row_to_entry(row) if row else None

    async def update_last_heard(self, entry_id: int, source: str, seen_at: str) -> None:
        await self._execute(
            "UPDATE roster SET last_heard_at = ?, last_heard_source = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (seen_at, source, entry_id),
        )
        await self._connection.commit()

    async def get_roster_version(self) -> str:
        row = await self._fetchone(
            "SELECT COALESCE(MAX(updated_at), '') AS latest, COUNT(*) AS count FROM roster"
        )
        return f"{row['latest']}|{row['count']}"

    async def get_setting(self, key: str) -> str | None:
        row = await self._fetchone("SELECT value FROM settings WHERE key = ?", (key,))
        return row["value"] if row else None

    async def set_setting(self, key: str, value: str) -> None:
        await self._execute(
            "INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        await self._connection.commit()

    async def get_filter(self) -> str:
        entries = await self.get_enabled_entries()
        tokens: list[str] = []
        for entry in entries:
            call = entry.aprs_call
            if entry.match_all_ssids:
                base = self._base_call(call)
                tokens.append(f"b/{base}*")
            else:
                tokens.append(call)
        if not tokens:
            return "filter N0CALL"
        return "filter " + "/".join(tokens)

    def _row_to_entry(self, row: aiosqlite.Row | None) -> RosterEntry | None:
        if row is None:
            return None
        return RosterEntry(
            id=row["id"],
            aprs_call=row["aprs_call"],
            enabled=bool(row["enabled"]),
            match_all_ssids=bool(row["match_all_ssids"]),
            tak_uid=row["tak_uid"],
            tak_display_name=row["tak_display_name"],
            tactical_call=row["tactical_call"],
            team=row["team"],
            role=row["role"],
            icon=row["icon"],
            remarks=row["remarks"],
            last_heard_at=row["last_heard_at"],
            last_heard_source=row["last_heard_source"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _normalize_call(aprs_call: str) -> str:
        return aprs_call.strip().upper()

    @staticmethod
    def _base_call(aprs_call: str) -> str:
        if "-" in aprs_call:
            return aprs_call.split("-", 1)[0]
        return aprs_call
