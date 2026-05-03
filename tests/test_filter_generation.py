import asyncio
import os
import tempfile

from aprs_tak_gateway.roster import RosterDB


def test_filter_generation_from_roster():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "roster.db")
        db = RosterDB(db_path)
        asyncio.run(db.initialize())
        asyncio.run(db._execute(
            "INSERT INTO roster(aprs_call, enabled, match_all_ssids, tak_uid, tak_display_name) VALUES (?, ?, ?, ?, ?)",
            ("K6ABC", 1, 1, "uid1", "K6 ABC"),
        ))
        asyncio.run(db._execute(
            "INSERT INTO roster(aprs_call, enabled, match_all_ssids, tak_uid, tak_display_name) VALUES (?, ?, ?, ?, ?)",
            ("N6XYZ-7", 1, 0, "uid2", "N6 XYZ"),
        ))
        asyncio.run(db._connection.commit())

        filter_text = asyncio.run(db.get_filter())
        assert "b/K6ABC*" in filter_text
        assert "N6XYZ-7" in filter_text
        assert filter_text.startswith("filter ")
