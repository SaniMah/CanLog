"""Tests for the candump log parser (src/load.load_candump)."""
from src.load import load_candump


def test_parses_candump_lines(tmp_path):
    p = tmp_path / "sample.log"
    p.write_text(
        "(1000.000000) can0 420#3F0000334200F257\n"  # 8 data bytes
        "(1000.010000) can0 420#00\n"                 # 1 data byte
        "this is not a candump line\n"                # should be skipped
        "(1000.020000) can0 4D1#\n"                   # 0 data bytes (empty)
    )
    df = load_candump(str(p))

    assert len(df) == 3
    assert df.attrs["skipped_lines"] == 1
    assert list(df["can_id"]) == ["420", "420", "4D1"]
    assert list(df["dlc"]) == [8, 1, 0]
    assert df.iloc[0]["data"] == "3F0000334200F257"
    assert df.iloc[2]["data"] == ""


def test_interface_filter(tmp_path):
    p = tmp_path / "two_buses.log"
    p.write_text("(1.0) can0 100#00\n(1.1) can1 100#00\n")
    df = load_candump(str(p), interface="can0")
    assert len(df) == 1
    assert df.iloc[0]["iface"] == "can0"


def test_empty_file(tmp_path):
    p = tmp_path / "empty.log"
    p.write_text("")
    df = load_candump(str(p))
    assert len(df) == 0
    assert list(df.columns) == ["timestamp", "can_id", "data", "dlc", "iface"]
