import weakref

import pytest

import local_remote_control.media as media
from local_remote_control.media import MediaUnavailable, fallback_encoder, select_encoder


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


def test_hardware_encoder_falls_back_to_software_once() -> None:
    primary = select_encoder({"nvh264enc", "x264enc"})
    fallback = fallback_encoder(primary, {"nvh264enc", "x264enc"})
    assert fallback is not None and fallback.name == "x264enc"
    assert fallback_encoder(select_encoder({"x264enc"}), {"x264enc"}) is None


def test_offer_reply_stays_alive_until_its_borrowed_sdp_is_sent() -> None:
    sent: list[str] = []
    element = RecordingWebRtcElement()

    media._complete_offer(BorrowingPromise(), element, object(), sent.append)

    assert element.received_live_sdp
    assert sent == ["v=0\r\n"]


class BorrowingPromise:
    def get_reply(self):
        return OwningReply()


class OwningReply:
    def get_value(self, name: str):
        assert name == "offer"
        return BorrowedOffer(self)


class BorrowedOffer:
    def __init__(self, owner: OwningReply) -> None:
        self._owner = weakref.ref(owner)

    @property
    def sdp(self):
        return FakeSdp() if self._owner() is not None else None


class FakeSdp:
    def as_text(self) -> str:
        return "v=0\r\n"


class RecordingWebRtcElement:
    received_live_sdp = False

    def emit(self, signal: str, offer: BorrowedOffer, _promise: object) -> None:
        assert signal == "set-local-description"
        self.received_live_sdp = offer.sdp is not None
