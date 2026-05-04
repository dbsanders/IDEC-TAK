import asyncio
import logging
import struct
from datetime import datetime
from typing import Any

from .aprs_parser import parse_aprs_packet
from .cot import build_cot_xml
from .dedupe import Deduper
from .roster import RosterDB
from .tak_client import TakClient

logger = logging.getLogger(__name__)
AGW_HEADER = struct.Struct("<BBBBBBBB10s10sII")
AGW_MAX_DATA_LEN = 4096


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
        writer.write(self._build_header("m"))
        await writer.drain()

        try:
            while not self._stop:
                raw_header = await reader.readexactly(AGW_HEADER.size)
                frame = self._parse_frame_header(raw_header)
                data_len = frame["data_len"]
                if data_len > AGW_MAX_DATA_LEN:
                    raise ValueError(f"AGW frame data length too large: {data_len}")
                data = await reader.readexactly(data_len) if data_len else b""

                if frame["kind"] != "U":
                    continue

                payload = self._extract_monitor_payload(data)
                if not payload:
                    continue

                source = frame["from"]
                destination = frame["to"]
                if not source or not destination:
                    logger.debug("Ignored AGW monitor frame without callsigns")
                    continue

                packet = f"{source}>{destination}:{payload}"
                await self._process_packet(packet)
        except asyncio.IncompleteReadError:
            logger.warning("Dire Wolf AGW connection closed")
        finally:
            writer.close()
            await writer.wait_closed()

    @classmethod
    def _build_header(cls, kind: str, data_len: int = 0) -> bytes:
        return AGW_HEADER.pack(
            0,
            0,
            0,
            0,
            ord(kind),
            0,
            0,
            0,
            b"\x00" * 10,
            b"\x00" * 10,
            data_len,
            0,
        )

    @staticmethod
    def _decode_call(value: bytes) -> str:
        return value.split(b"\x00", 1)[0].decode("ascii", errors="ignore").strip()

    @classmethod
    def _parse_frame_header(cls, raw_header: bytes) -> dict[str, Any]:
        (
            port,
            _reserved1,
            _reserved2,
            _reserved3,
            kind,
            _reserved4,
            _pid,
            _reserved5,
            call_from,
            call_to,
            data_len,
            _user_reserved,
        ) = AGW_HEADER.unpack(raw_header)
        return {
            "port": port,
            "kind": chr(kind),
            "from": cls._decode_call(call_from),
            "to": cls._decode_call(call_to),
            "data_len": data_len,
        }

    @staticmethod
    def _extract_monitor_payload(data: bytes) -> str | None:
        text = data.rstrip(b"\x00").decode("utf-8", errors="ignore")
        if "\r" in text:
            _header, payload = text.split("\r", 1)
        elif "\n" in text:
            _header, payload = text.split("\n", 1)
        else:
            payload = text
        payload = payload.strip()
        return payload or None

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
        await self.roster_db.update_last_heard(roster_entry.id, "RF", datetime.utcnow().isoformat())
        logger.info("Sent %s via RF", parsed.source)
