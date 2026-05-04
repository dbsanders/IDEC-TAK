import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

POSITION_RE = re.compile(
    r"^(?P<latdeg>\d{2})(?P<latmin>\d{2}\.\d{2})(?P<latdir>[NS])"
    r"(?P<symtab>.)(?P<londeg>\d{3})(?P<lonmin>\d{2}\.\d{2})(?P<londir>[EW])(?P<symcode>.)"
)
COURSE_SPEED_RE = re.compile(r"(?P<course>\d{3})/(?P<speed>\d{3})")
ALTITUDE_RE = re.compile(r"A=(?P<alt>\d{6})")
TIMESTAMP_RE = re.compile(r"^(?P<dd>\d{2})(?P<hh>\d{2})(?P<mm>\d{2})(?P<t>[z/\@h])")


@dataclass
class AprsPosition:
    source: str
    destination: str
    latitude: float
    longitude: float
    symbol_table: str | None
    symbol_code: str | None
    course: int | None
    speed: int | None
    altitude: int | None
    comment: str | None
    timestamp: str | None
    source_type: str
    raw: str


def normalize_call(call: str) -> str:
    return call.strip().upper()


def parse_aprs_packet(raw_packet: str, source_type: str) -> AprsPosition | None:
    raw_packet = raw_packet.strip()
    if ">" not in raw_packet or ":" not in raw_packet:
        return None

    source, remainder = raw_packet.split(">", 1)
    destination, payload = remainder.split(":", 1)
    source = normalize_call(source)
    destination = normalize_call(destination)

    if not payload:
        return None

    symbol = payload[0]
    if symbol not in "!=/@":
        return None

    timestamp = None
    position_payload = payload[1:]
    if symbol in "/@":
        match = TIMESTAMP_RE.match(position_payload)
        if match:
            timestamp = position_payload[:7]
            position_payload = position_payload[7:]

    pos_match = POSITION_RE.match(position_payload)
    if not pos_match:
        return None

    latitude = _decode_latitude(
        int(pos_match.group("latdeg")),
        float(pos_match.group("latmin")),
        pos_match.group("latdir"),
    )
    longitude = _decode_longitude(
        int(pos_match.group("londeg")),
        float(pos_match.group("lonmin")),
        pos_match.group("londir"),
    )

    remainder_index = pos_match.end()
    remainder_text = position_payload[remainder_index:].lstrip()
    comment_text = remainder_text
    course = None
    speed = None
    altitude = None

    cs_match = COURSE_SPEED_RE.search(comment_text)
    if cs_match:
        course = int(cs_match.group("course"))
        speed = int(cs_match.group("speed"))
        if cs_match.start() == 0:
            comment_text = comment_text[cs_match.end():]

    alt_match = ALTITUDE_RE.search(comment_text)
    if alt_match:
        altitude = int(alt_match.group("alt"))
        leading_alt_match = re.match(r"/?A=(?P<alt>\d{6})", comment_text)
        if leading_alt_match:
            comment_text = comment_text[leading_alt_match.end():]

    comment = comment_text.strip() or None
    return AprsPosition(
        source=source,
        destination=destination,
        latitude=latitude,
        longitude=longitude,
        symbol_table=pos_match.group("symtab"),
        symbol_code=pos_match.group("symcode"),
        course=course,
        speed=speed,
        altitude=altitude,
        comment=comment,
        timestamp=timestamp,
        source_type=source_type,
        raw=raw_packet,
    )


def _decode_latitude(deg: int, minutes: float, direction: str) -> float:
    value = deg + minutes / 60.0
    if direction == "S":
        value = -value
    return round(value, 6)


def _decode_longitude(deg: int, minutes: float, direction: str) -> float:
    value = deg + minutes / 60.0
    if direction == "W":
        value = -value
    return round(value, 6)
