import asyncio
import logging
from datetime import datetime
from typing import Any

from .aprs_parser import parse_aprs_packet
from .cot import build_cot_xml
from .dedupe import Deduper
from .roster import RosterDB
from .tak_client import TakClient

logger = logging.getLogger(__name__)


class AprsIsClient:
    def __init__(self, config: dict[str, Any], gateway_config: dict[str, Any], roster_db: RosterDB, deduper: Deduper, tak_client: TakClient):
        self.config = config
        self.gateway_config = gateway_config
        self.roster_db = roster_db
        self.deduper = deduper
        self.tak_client = tak_client
        self._stop = False
        self._roster_version = ""
        self._reload_requested = ""

    async def run(self) -> None:
        while not self._stop:
            try:
                await self._connect_and_run()
            except Exception as exc:  # pylint: disable=broad-except
                logger.error("APRS-IS client error: %s", exc)
                await asyncio.sleep(5)

    async def stop(self) -> None:
        self._stop = True

    async def _connect_and_run(self) -> None:
        roster_version = await self.roster_db.get_roster_version()
        filter_text = await self.roster_db.get_filter()
        login_call = self.config["login_call"]
        passcode = self.config["passcode"]
        app_name = self.config.get("app_name", "aprs-tak-gw")
        app_version = self.config.get("app_version", "0.1")
        hostname = self.config["server"]
        port = int(self.config["port"])

        logger.info("Connecting to APRS-IS %s:%s", hostname, port)
        reader, writer = await asyncio.open_connection(hostname, port)
        login_line = f"user {login_call} pass {passcode} vers {app_name} {app_version} {filter_text}\n"
        writer.write(login_line.encode("utf-8"))
        await writer.drain()
        logger.info("APRS-IS connected and login sent")

        self._roster_version = roster_version
        self._reload_requested = await self.roster_db.get_setting("aprsis_reload_token") or ""
        next_roster_check = datetime.utcnow().timestamp() + self.gateway_config.get("roster_poll_seconds", 30)

        while not self._stop:
            try:
                raw_line = await asyncio.wait_for(reader.readline(), timeout=90)
            except asyncio.TimeoutError:
                raw_line = b""

            if not raw_line:
                logger.warning("APRS-IS connection closed by server")
                break

            line = raw_line.decode("utf-8", errors="ignore").strip()
            if not line or line.startswith("#"):
                continue

            await self._process_line(line)

            if datetime.utcnow().timestamp() >= next_roster_check:
                next_roster_check = datetime.utcnow().timestamp() + self.gateway_config.get("roster_poll_seconds", 30)
                current_version = await self.roster_db.get_roster_version()
                reload_token = await self.roster_db.get_setting("aprsis_reload_token") or ""
                if current_version != self._roster_version or reload_token != self._reload_requested:
                    logger.info("Roster or reload token changed, reconnecting APRS-IS")
                    break

        writer.close()
        await writer.wait_closed()

    async def _process_line(self, line: str) -> None:
        parsed = parse_aprs_packet(line, source_type="APRS-IS")
        if not parsed:
            logger.debug("Ignored unparsable APRS-IS packet: %s", line)
            return

        roster_entry = await self.roster_db.find_entry_for_aprs_call(parsed.source)
        if roster_entry is None:
            logger.info("Ignored %s, not in roster", parsed.source)
            return

        key = self.deduper.make_key(parsed.source, parsed.latitude, parsed.longitude, parsed.comment, parsed.timestamp)
        if self.deduper.is_duplicate(key, parsed.source_type):
            logger.debug("Duplicate APRS-IS packet ignored: %s", parsed.source)
            return

        xml = build_cot_xml(
            tak_uid=roster_entry.tak_uid,
            display_name=roster_entry.display_name,
            latitude=parsed.latitude,
            longitude=parsed.longitude,
            altitude_feet=parsed.altitude,
            comment=parsed.comment,
            original_aprs=parsed.raw,
            stale_minutes=int(self.gateway_config.get("stale_minutes", 10)),
        )

        await self.tak_client.send_event(xml)
        await self.roster_db.update_last_heard(roster_entry.id, "APRS-IS", datetime.utcnow().isoformat())
        logger.info("Sent %s via APRS-IS", parsed.source)
