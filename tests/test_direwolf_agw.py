from aprs_tak_gateway.direwolf_agw import AGW_HEADER, DirewolfAgwClient


def test_build_header_sends_monitor_command():
    header = DirewolfAgwClient._build_header("m")

    fields = AGW_HEADER.unpack(header)
    assert fields[4] == ord("m")
    assert fields[10] == 0


def test_parse_agw_monitor_frame_header():
    raw_header = AGW_HEADER.pack(
        0,
        0,
        0,
        0,
        ord("U"),
        0,
        0xF0,
        0,
        b"N6ZAR-2\x00\x00\x00",
        b"APAT81\x00\x00\x00\x00",
        81,
        0,
    )

    frame = DirewolfAgwClient._parse_frame_header(raw_header)

    assert frame == {
        "port": 0,
        "kind": "U",
        "from": "N6ZAR-2",
        "to": "APAT81",
        "data_len": 81,
    }


def test_extract_monitor_payload_from_direwolf_frame_data():
    data = (
        b" 1:Fm N6ZAR-2 To APAT81 <UI pid=F0 Len=68 PF=0 >[17:37:17]\r"
        b"!3409.94N/11809.49Wk183/018/A=000853Hi, have a great day!\r\x00"
    )

    payload = DirewolfAgwClient._extract_monitor_payload(data)

    assert payload == "!3409.94N/11809.49Wk183/018/A=000853Hi, have a great day!"
