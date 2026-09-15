import pytest

from local_remote_control.media import MediaUnavailable, select_encoder


def test_prefers_nvenc_then_vaapi_then_software() -> None:
    assert select_encoder({"nvh264enc", "vah264enc", "x264enc"}).name == "nvh264enc"
    assert select_encoder({"vah264enc", "x264enc"}).name == "vah264enc"
    software = select_encoder({"x264enc"})
    assert software.name == "x264enc"
    assert not software.hardware
    assert "zerolatency" in software.pipeline_fragment


def test_requires_at_least_one_supported_encoder() -> None:
    with pytest.raises(MediaUnavailable, match="H.264"):
        select_encoder(set())
