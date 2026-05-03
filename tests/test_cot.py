from aprs_tak_gateway.cot import build_cot_xml


def test_build_cot_xml_contains_uid_and_coordinates():
    xml = build_cot_xml(
        tak_uid="aprs.K6ABC-7",
        display_name="TAC-12",
        latitude=34.165667,
        longitude=-118.158167,
        altitude_feet=853,
        comment="Test unit",
        original_aprs="K6ABC-7>APRS:!3409.94N/11809.49Wk...",
        stale_minutes=10,
    )

    assert "uid=\"aprs.K6ABC-7\"" in xml
    assert "lat=\"34.165667\"" in xml
    assert "lon=\"-118.158167\"" in xml
    assert "TAC-12" in xml
    assert "Test unit" in xml
    assert "__original_aprs" in xml
