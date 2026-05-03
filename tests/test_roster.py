import asyncio
import os
import tempfile

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
