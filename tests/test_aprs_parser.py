import pytest

from aprs_tak_gateway.aprs_parser import parse_aprs_packet


def test_parse_aprs_position_packet():
    raw = "N6ZAR-2>APAT81:!3409.94N/11809.49Wk183/018/A=000853Hi, have a great day!"
    parsed = parse_aprs_packet(raw, source_type="RF")

    assert parsed is not None
    assert parsed.source == "N6ZAR-2"
    assert parsed.destination == "APAT81"
    assert pytest.approx(parsed.latitude, rel=1e-5) == 34.165667
    assert pytest.approx(parsed.longitude, rel=1e-5) == -118.158167
    assert parsed.course == 183
    assert parsed.speed == 18
    assert parsed.altitude == 853
    assert parsed.comment == "Hi, have a great day!"
    assert parsed.source_type == "RF"


def test_parse_aprs_with_timestamp():
    raw = "K6ABC>APRS:@091014z3409.94N/11809.49W>`Hello"
    parsed = parse_aprs_packet(raw, source_type="APRS-IS")

    assert parsed is not None
    assert parsed.timestamp == "091014z"
    assert parsed.source == "K6ABC"
    assert parsed.source_type == "APRS-IS"
