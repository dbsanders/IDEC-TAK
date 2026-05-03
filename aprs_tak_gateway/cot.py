from datetime import datetime, timedelta
from xml.sax.saxutils import escape


def build_cot_xml(
    source_call: str,
    display_name: str,
    latitude: float,
    longitude: float,
    altitude_feet: int | None,
    comment: str | None,
    original_aprs: str,
    stale_minutes: int,
) -> str:
    event_time = datetime.utcnow()
    stale_time = event_time + timedelta(minutes=stale_minutes)
    uid = f"aprs.{source_call}"
    hae = _convert_altitude_to_meters(altitude_feet)
    remark_text = comment or ""

    return (
        f"<event version=\"2.0\" uid=\"{escape(uid)}\" type=\"a-n-G\" how=\"m-g\" "
        f"time=\"{event_time.isoformat()}Z\" start=\"{event_time.isoformat()}Z\" "
        f"stale=\"{stale_time.isoformat()}Z\">"
        f"<point lat=\"{latitude:.6f}\" lon=\"{longitude:.6f}\" hae=\"{hae:.1f}\" ce=\"9999999.0\" le=\"9999999.0\"/>"
        f"<detail>"
        f"<contact callsign=\"{escape(display_name)}\"/>"
        f"<remarks>{escape(remark_text)}</remarks>"
        f"<__original_aprs>{escape(original_aprs)}</__original_aprs>"
        f"</detail>"
        f"</event>"
    )


def _convert_altitude_to_meters(altitude_feet: int | None) -> float:
    if altitude_feet is None:
        return 0.0
    return altitude_feet * 0.3048
