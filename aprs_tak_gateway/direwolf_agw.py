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


class DirewolfAgwClient:
    def __init__(self, config: dict[str, Any], gateway_config: dict[str, Any], roster_db: RosterDB, deduper: Deduper, tak_client: TakClient):
        self.config = config
        self.gateway_config = gateway_config
        self.roster_db = roster_db
        self.deduper = deduper
        self.tak_client = tak_client
        self._stop = False

    async def run(self) -> None:
        while not self._stop:
            try:
                await self._connect_and_run()
            except Exception as exc:  # pylint: disable=broad-except
                logger.error("Dire Wolf AGW client error: %s", exc)
                await asyncio.sleep(5)

    async def stop(self) -> None:
        self._stop = True

    async def _connect_and_run(self) -> None:
        host = self.config["host"]
        port = int(self.config["port"])
        logger.info("Connecting to Dire Wolf AGW %s:%s", host, port)
        reader, writer = await asyncio.open_connection(host, port)
        logger.info("Dire Wolf AGW connected")

        current_header: dict[str, str] = {}
        while not self._stop:
            raw_line = await reader.readline()
            if not raw_line:
                logger.warning("Dire Wolf AGW connection closed")
                break

            line = raw_line.decode("utf-8", errors="ignore").strip()
            if line.startswith("[AGW"):
                current_header = self._parse_header(line)
                continue

            if current_header and current_header.get("from") and current_header.get("to"):
                packet = f"{current_header['from']}>{current_header['to']}:{line}"
                await self._process_packet(packet)
                current_header = {}

        writer.close()
        await writer.wait_closed()

    async def _process_packet(self, packet: str) -> None:
        parsed = parse_aprs_packet(packet, source_type="RF")
        if not parsed:
            logger.debug("Ignored unparsable RF packet: %s", packet)
            return

        roster_entry = await self.roster_db.find_entry_for_aprs_call(parsed.source)
        if roster_entry is None:
            logger.info("Ignored %s, not in roster", parsed.source)
            return

        key = self.deduper.make_key(parsed.source, parsed.latitude, parsed.longitude, parsed.comment, parsed.timestamp)
        if self.deduper.is_duplicate(key, parsed.source_type):
            logger.debug("Duplicate RF packet ignored: %s", parsed.source)
            return

        xml = build_cot_xml(
            source_call=parsed.source,
            display_name=roster_entry.display_name,
            latitude=parsed.latitude,
            longitude=parsed.longitude,
            altitude_feet=parsed.altitude,
            comment=parsed.comment,
            original_aprs=parsed.raw,
            stale_minutes=int(self.gateway_config.get("stale_minutes", 10)),
        )
        await self.tak_client.send_event(xml)
        await self.roster_db.update_last_heard(roster_entry.id, "RF", datetime.utcnow().isoformat())
        logger.info("Sent %s via RF", parsed.source)

    @staticmethod
    def _parse_header(header: str) -> dict[str, str]:
        fields = {}
        for part in header.strip("[]").split():
            if "=" in part:
                key, _, value = part.partition("=")
                fields[key] = value
        return fields
