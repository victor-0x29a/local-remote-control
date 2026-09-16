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


@pytest.mark.parametrize("encoder_name", ["nvh264enc", "vah264enc", "vaapih264enc", "x264enc"])
def test_pipeline_converts_x11_frames_to_common_encoder_format(encoder_name: str) -> None:
    encoder = select_encoder({encoder_name})
    description = media._pipeline_description(encoder, ":0", 30)

    assert "videoconvert ! video/x-raw,format=NV12 !" in description
    assert encoder_name in description
    assert (
        f"{encoder.pipeline_fragment} ! video/x-h264,profile=constrained-baseline ! h264parse"
        in description
    )


def test_glib_main_context_starts_one_daemon_thread() -> None:
    loops: list[FakeMainLoop] = []
    threads: list[FakeThread] = []
    context = media._GlibMainContext(
        thread_factory=lambda **options: threads.append(FakeThread(**options)) or threads[-1]
    )

    context.ensure(FakeGlib(loops))
    context.ensure(FakeGlib(loops))

    assert len(loops) == 1
    assert len(threads) == 1
    assert threads[0].daemon is True
    assert threads[0].name == "local-remote-control-glib"
    assert threads[0].started


def test_glib_main_context_dispatches_calls() -> None:
    context = media._GlibMainContext(thread_factory=FakeThread)
    glib = FakeGlib([])
    context.ensure(glib)

    assert context.call(lambda: "dispatched") == "dispatched"
    assert glib.dispatched == 1


def test_stop_invalidates_a_queued_encoder_fallback() -> None:
    notices: list[str] = []
    primary = select_encoder({"vaapih264enc"})
    desktop = media.WebRtcDesktop(
        primary,
        on_offer=lambda _: None,
        on_ice=lambda *_: None,
        on_error=notices.append,
        fallback=select_encoder({"x264enc"}),
    )
    teardown: list[str] = []
    desktop._active = True
    desktop._generation = 4
    desktop._teardown_on_context = lambda: teardown.append("teardown")

    desktop._stop_on_context()
    desktop._handle_error_on_context(None, UnexpectedMessage(), 4)

    assert teardown == ["teardown"]
    assert desktop.encoder is primary
    assert notices == []


def test_current_encoder_error_switches_to_fallback_once() -> None:
    notices: list[str] = []
    fallback = select_encoder({"x264enc"})
    desktop = media.WebRtcDesktop(
        select_encoder({"vaapih264enc"}),
        on_offer=lambda _: None,
        on_ice=lambda *_: None,
        on_error=notices.append,
        fallback=fallback,
    )
    lifecycle: list[str] = []
    desktop._active = True
    desktop._generation = 2
    desktop._teardown_on_context = lambda: lifecycle.append("teardown")
    desktop._start_pipeline_on_context = lambda: lifecycle.append("start")

    desktop._handle_error_on_context(None, ErrorMessage("hardware failure"), 2)

    assert desktop.encoder is fallback
    assert desktop._generation == 3
    assert lifecycle == ["teardown", "start"]
    assert notices == ["encoder vaapih264enc falhou; alternando para x264enc"]


def test_pipeline_teardown_disconnects_handlers_and_bus_watch() -> None:
    desktop = media.WebRtcDesktop(
        select_encoder({"x264enc"}),
        on_offer=lambda _: None,
        on_ice=lambda *_: None,
        on_error=lambda _: None,
    )
    pipeline = FakePipeline()
    bus = FakeBus()
    source = FakeSignalSource()
    desktop._gst = FakeGst()
    desktop._pipeline = pipeline
    desktop._webrtc = source
    desktop._bus = bus
    desktop._signal_handlers = [(source, 7), (bus, 8)]

    desktop._teardown_on_context()

    assert source.disconnected == [7]
    assert bus.disconnected == [8]
    assert bus.watch_removed
    assert pipeline.states == ["null"]
    assert desktop._pipeline is desktop._webrtc is desktop._bus is None


def test_stale_browser_answer_and_ice_are_ignored() -> None:
    desktop = media.WebRtcDesktop(
        select_encoder({"x264enc"}),
        on_offer=lambda *_: None,
        on_ice=lambda *_: None,
        on_error=lambda _: None,
    )
    desktop._active = True
    desktop._generation = 9
    desktop._webrtc = UnexpectedSignalSource()

    assert desktop._set_remote_answer_on_context("v=0", 8) is False
    assert desktop._add_ice_on_context("candidate", 0, 8) is False


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


class FakeMainLoop:
    def run(self) -> None:
        pass


class FakeGlib:
    def __init__(self, loops: list[FakeMainLoop]) -> None:
        self._loops = loops
        self.dispatched = 0

    def MainLoop(self) -> FakeMainLoop:
        loop = FakeMainLoop()
        self._loops.append(loop)
        return loop

    def idle_add(self, callback):
        self.dispatched += 1
        callback()


class FakeThread:
    def __init__(self, *, target, name: str, daemon: bool) -> None:
        self.target = target
        self.name = name
        self.daemon = daemon
        self.started = False

    def start(self) -> None:
        self.started = True

    def is_alive(self) -> bool:
        return self.started


class UnexpectedMessage:
    def parse_error(self):
        raise AssertionError("a stale pipeline message must be ignored")


class ErrorMessage:
    def __init__(self, message: str) -> None:
        self._message = message

    def parse_error(self):
        return type("NativeError", (), {"message": self._message})(), None


class FakeSignalSource:
    def __init__(self) -> None:
        self.disconnected: list[int] = []

    def disconnect(self, handler: int) -> None:
        self.disconnected.append(handler)


class UnexpectedSignalSource:
    def emit(self, *_):
        raise AssertionError("stale browser signaling must be ignored")


class FakeBus(FakeSignalSource):
    def __init__(self) -> None:
        super().__init__()
        self.watch_removed = False

    def remove_signal_watch(self) -> None:
        self.watch_removed = True


class FakePipeline:
    def __init__(self) -> None:
        self.states: list[str] = []

    def set_state(self, state: str) -> None:
        self.states.append(state)


class FakeGst:
    class State:
        NULL = "null"
