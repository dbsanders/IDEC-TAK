import asyncio
import os
import sqlite3
import tempfile

import pytest

from aprs_tak_gateway.roster import RosterDB


def test_find_entry_matches_exact_and_base():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "roster.db")
        db = RosterDB(db_path)
        asyncio.run(db.initialize())
        asyncio.run(db._execute(
            "INSERT INTO roster(aprs_call, enabled, match_all_ssids, tak_uid, tak_display_name) VALUES (?, ?, ?, ?, ?)",
            ("K6ABC", 1, 1, "uid1", "Base"),
        ))
        asyncio.run(db._execute(
            "INSERT INTO roster(aprs_call, enabled, match_all_ssids, tak_uid, tak_display_name) VALUES (?, ?, ?, ?, ?)",
            ("K6ABC-7", 1, 0, "uid2", "Exact"),
        ))
        asyncio.run(db._connection.commit())

        exact = asyncio.run(db.find_entry_for_aprs_call("K6ABC-7"))
        assert exact is not None
        assert exact.tak_uid == "uid2"

        base = asyncio.run(db.find_entry_for_aprs_call("K6ABC-9"))
        assert base is not None
        assert base.tak_uid == "uid1"
        asyncio.run(db.close())


def test_find_entry_matches_callsigns_case_insensitively():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "roster.db")
        db = RosterDB(db_path)
        asyncio.run(db.initialize())
        asyncio.run(db._execute(
            "INSERT INTO roster(aprs_call, enabled, match_all_ssids, tak_uid, tak_display_name) VALUES (?, ?, ?, ?, ?)",
            ("k6abc-7", 1, 0, "uid1", "K6 ABC"),
        ))
        asyncio.run(db._connection.commit())

        entry = asyncio.run(db.find_entry_for_aprs_call("K6ABC-7"))

        assert entry is not None
        assert entry.tak_uid == "uid1"
        asyncio.run(db.close())


def test_initialize_migrates_removed_tak_fields():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "roster.db")
        db = RosterDB(db_path)
        asyncio.run(db.initialize())
        asyncio.run(db._execute("ALTER TABLE roster ADD COLUMN team TEXT"))
        asyncio.run(db._execute("ALTER TABLE roster ADD COLUMN role TEXT"))
        asyncio.run(db._execute("ALTER TABLE roster ADD COLUMN icon TEXT"))
        asyncio.run(db._connection.commit())
        asyncio.run(db.close())

        db = RosterDB(db_path)
        asyncio.run(db.initialize())
        rows = asyncio.run(db._fetchall("PRAGMA table_info(roster)"))

        column_names = {row["name"] for row in rows}
        assert "team" not in column_names
        assert "role" not in column_names
        assert "icon" not in column_names
        asyncio.run(db.close())


def test_display_name_falls_back_to_tak_display_name():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "roster.db")
        db = RosterDB(db_path)
        asyncio.run(db.initialize())
        asyncio.run(db._execute(
            "INSERT INTO roster(aprs_call, enabled, match_all_ssids, tak_uid, tak_display_name) VALUES (?, ?, ?, ?, ?)",
            ("K6ABC", 1, 1, "uid1", "Engine 12"),
        ))
        asyncio.run(db._connection.commit())

        entry = asyncio.run(db.find_entry_for_aprs_call("K6ABC"))

        assert entry is not None
        assert entry.display_name == "Engine 12"
        asyncio.run(db.close())


def test_initialize_rejects_case_variant_duplicate_calls_during_migration():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "roster.db")
        connection = sqlite3.connect(db_path)
        connection.execute(
            """
            CREATE TABLE roster (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                aprs_call TEXT NOT NULL UNIQUE,
                enabled INTEGER NOT NULL DEFAULT 1,
                match_all_ssids INTEGER NOT NULL DEFAULT 1,
                tak_uid TEXT NOT NULL UNIQUE,
                tak_display_name TEXT NOT NULL,
                tactical_call TEXT,
                team TEXT,
                remarks TEXT,
                last_heard_at TEXT,
                last_heard_source TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.execute(
            "INSERT INTO roster(aprs_call, enabled, match_all_ssids, tak_uid, tak_display_name) VALUES (?, ?, ?, ?, ?)",
            ("K6ABC", 1, 1, "uid1", "Upper"),
        )
        connection.execute(
            "INSERT INTO roster(aprs_call, enabled, match_all_ssids, tak_uid, tak_display_name) VALUES (?, ?, ?, ?, ?)",
            ("k6abc", 1, 1, "uid2", "Lower"),
        )
        connection.commit()
        connection.close()

        db = RosterDB(db_path)
        with pytest.raises(RuntimeError, match="case-variant duplicate APRS calls"):
            asyncio.run(db.initialize())
        asyncio.run(db.close())
