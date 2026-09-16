"""Native low-latency X11 capture and WebRTC media pipeline."""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from typing import Callable


class MediaUnavailable(RuntimeError):
    pass


class _GlibMainContext:
    def __init__(self, thread_factory=threading.Thread) -> None:
        self._thread_factory = thread_factory
        self._lock = threading.Lock()
        self._glib = None
        self._loop = None
        self._thread = None
        self._thread_ident = None

    def ensure(self, glib) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            loop = glib.MainLoop()
            thread = self._thread_factory(
                target=self._run,
                name="local-remote-control-glib",
                daemon=True,
            )
            self._glib = glib
            self._loop = loop
            self._thread = thread
            thread.start()

    def _run(self) -> None:
        self._thread_ident = threading.get_ident()
        try:
            self._loop.run()
        finally:
            self._thread_ident = None

    def call(self, callback):
        if threading.get_ident() == self._thread_ident:
            return callback()
        completed = threading.Event()
        outcome = []

        def invoke() -> bool:
            try:
                outcome.append((True, callback()))
            except BaseException as error:
                outcome.append((False, error))
            finally:
                completed.set()
            return False

        self._glib.idle_add(invoke)
        if not completed.wait(timeout=10):
            raise MediaUnavailable("GLib main context did not respond")
        succeeded, value = outcome[0]
        if not succeeded:
            raise value
        return value


_glib_main_context = _GlibMainContext()


def _complete_offer(promise, element, local_description_promise, on_offer: Callable[[str], None]) -> None:
    reply = promise.get_reply()
    offer = reply.get_value("offer")
    element.emit("set-local-description", offer, local_description_promise)
    on_offer(offer.sdp.as_text())


@dataclass(frozen=True, slots=True)
class Encoder:
    name: str
    pipeline_fragment: str
    hardware: bool


def _pipeline_description(encoder: Encoder, display: str, fps: int) -> str:
    return (
        f"ximagesrc display-name={display} use-damage=true show-pointer=true ! "
        f"video/x-raw,framerate={fps}/1 ! videoconvert ! video/x-raw,format=NV12 ! "
        "queue max-size-buffers=1 leaky=downstream ! "
        f"{encoder.pipeline_fragment} ! video/x-h264,profile=constrained-baseline ! "
        "h264parse config-interval=-1 ! "
        "rtph264pay config-interval=-1 pt=96 ! application/x-rtp,media=video,encoding-name=H264,payload=96 ! "
        "webrtcbin name=sendrecv bundle-policy=max-bundle"
    )


def select_encoder(available: set[str], bitrate_kbps: int = 8_000, fps: int = 30) -> Encoder:
    if not 250 <= bitrate_kbps <= 50_000 or not 10 <= fps <= 60:
        raise ValueError("media settings are out of range")
    if "nvh264enc" in available:
        return Encoder("nvh264enc", f"nvh264enc preset=low-latency-hq rc-mode=cbr bitrate={bitrate_kbps} gop-size={fps}", True)
    if "vah264enc" in available:
        return Encoder("vah264enc", f"vah264enc bitrate={bitrate_kbps} key-int-max={fps} b-frames=0", True)
    if "vaapih264enc" in available:
        return Encoder("vaapih264enc", f"vaapih264enc bitrate={bitrate_kbps} keyframe-period={fps}", True)
    if "x264enc" in available:
        return Encoder("x264enc", f"x264enc tune=zerolatency speed-preset=ultrafast bitrate={bitrate_kbps} key-int-max={fps} bframes=0", False)
    raise MediaUnavailable("no supported H.264 encoder is installed")


def fallback_encoder(primary: Encoder, available: set[str], bitrate_kbps: int = 8_000, fps: int = 30) -> Encoder | None:
    if primary.hardware and "x264enc" in available:
        return select_encoder({"x264enc"}, bitrate_kbps, fps)
    return None


def probe_encoders() -> set[str]:
    try:
        import gi
        gi.require_version("Gst", "1.0")
        from gi.repository import Gst
    except (ImportError, ValueError) as error:
        raise MediaUnavailable("GStreamer Python bindings are unavailable") from error
    Gst.init(None)
    return {name for name in ("nvh264enc", "vah264enc", "vaapih264enc", "x264enc") if Gst.ElementFactory.find(name)}


class WebRtcDesktop:
    """One GStreamer WebRTC sender; all GI imports stay at the native boundary."""

    def __init__(
        self,
        encoder: Encoder,
        on_offer: Callable[[int, str], None],
        on_ice: Callable[[int, int, str], None],
        on_error: Callable[[str], None],
        *,
        fallback: Encoder | None = None,
        display: str = ":0",
        fps: int = 30,
    ) -> None:
        self.encoder = encoder
        self._on_offer = on_offer
        self._on_ice = on_ice
        self._on_error = on_error
        self._fallback = fallback
        self._fallback_used = False
        self._display = display
        self._fps = fps
        self._active = False
        self._generation = 0
        self._gst = None
        self._pipeline = None
        self._webrtc = None
        self._bus = None
        self._signal_handlers = []

    def start(self) -> None:
        try:
            import gi
            gi.require_version("Gst", "1.0")
            gi.require_version("GstWebRTC", "1.0")
            from gi.repository import GLib, Gst, GstWebRTC
        except (ImportError, ValueError) as error:
            raise MediaUnavailable("GStreamer WebRTC bindings are unavailable") from error
        Gst.init(None)
        _glib_main_context.ensure(GLib)
        self._gst = Gst
        _glib_main_context.call(self._start_on_context)

    def _start_on_context(self) -> None:
        if self._active:
            return
        self._active = True
        self._generation += 1
        try:
            self._start_pipeline_on_context()
        except Exception as error:
            if not self._switch_to_fallback_on_context(str(error)):
                self._active = False
                self._generation += 1
                self._teardown_on_context()
                raise

    def _start_pipeline_on_context(self) -> None:
        Gst = self._gst
        description = _pipeline_description(self.encoder, self._display, self._fps)
        self._pipeline = Gst.parse_launch(description)
        self._webrtc = self._pipeline.get_by_name("sendrecv")
        if self._webrtc is None:
            raise MediaUnavailable("WebRTC pipeline element is unavailable")
        generation = self._generation
        negotiation_handler = self._webrtc.connect(
            "on-negotiation-needed", lambda element: self._create_offer(element, generation)
        )
        ice_handler = self._webrtc.connect(
            "on-ice-candidate",
            lambda _, index, candidate: self._emit_ice(index, candidate, generation),
        )
        self._signal_handlers.extend(
            [(self._webrtc, negotiation_handler), (self._webrtc, ice_handler)]
        )
        bus = self._pipeline.get_bus()
        bus.add_signal_watch()
        error_handler = bus.connect(
            "message::error",
            lambda source, message: self._handle_error_on_context(source, message, generation),
        )
        self._bus = bus
        self._signal_handlers.append((bus, error_handler))
        state = self._pipeline.set_state(Gst.State.PLAYING)
        if state == Gst.StateChangeReturn.FAILURE:
            raise MediaUnavailable(f"encoder {self.encoder.name} failed to start")

    def _handle_error_on_context(self, _, message, generation: int) -> None:
        if not self._active or generation != self._generation:
            return
        error = message.parse_error()[0].message
        try:
            if self._switch_to_fallback_on_context(error):
                return
        except Exception as fallback_error:
            error = str(fallback_error)
        self._active = False
        self._generation += 1
        self._teardown_on_context()
        self._on_error(error)

    def _switch_to_fallback_on_context(self, _error: str) -> bool:
        if self._fallback is None or self._fallback_used:
            return False
        self._fallback_used = True
        failed = self.encoder.name
        self._generation += 1
        self._teardown_on_context()
        self.encoder = self._fallback
        self._on_error(f"encoder {failed} falhou; alternando para {self.encoder.name}")
        self._start_pipeline_on_context()
        return True

    def _emit_ice(self, index: int, candidate: str, generation: int) -> None:
        def emit() -> None:
            if self._active and generation == self._generation:
                self._on_ice(generation, index, candidate)

        _glib_main_context.call(emit)

    def _create_offer(self, element, generation: int) -> None:
        def create() -> None:
            if not self._active or generation != self._generation:
                return
            promise = self._gst.Promise.new_with_change_func(
                self._offer_created, (element, generation), None
            )
            element.emit("create-offer", None, promise)

        _glib_main_context.call(create)

    def _offer_created(self, promise, context, _) -> None:
        element, generation = context

        def complete() -> None:
            if self._active and generation == self._generation:
                _complete_offer(
                    promise,
                    element,
                    self._gst.Promise.new(),
                    lambda sdp: self._on_offer(generation, sdp),
                )

        _glib_main_context.call(complete)

    def set_remote_answer(self, sdp: str, generation: int) -> bool:
        return _glib_main_context.call(
            lambda: self._set_remote_answer_on_context(sdp, generation)
        )

    def _set_remote_answer_on_context(self, sdp: str, generation: int) -> bool:
        if not self._active or self._webrtc is None:
            raise MediaUnavailable("media pipeline has not started")
        if generation != self._generation:
            return False
        from gi.repository import GstSdp, GstWebRTC
        _, message = GstSdp.SDPMessage.new()
        if GstSdp.sdp_message_parse_buffer(sdp.encode(), message) != GstSdp.SDPResult.OK:
            raise MediaUnavailable("invalid SDP answer")
        answer = GstWebRTC.WebRTCSessionDescription.new(
            GstWebRTC.WebRTCSDPType.ANSWER, message
        )
        self._webrtc.emit("set-remote-description", answer, self._gst.Promise.new())
        return True

    def add_ice(self, candidate: str, mline: int, generation: int) -> bool:
        return _glib_main_context.call(
            lambda: self._add_ice_on_context(candidate, mline, generation)
        )

    def _add_ice_on_context(self, candidate: str, mline: int, generation: int) -> bool:
        if not self._active or self._webrtc is None:
            raise MediaUnavailable("media pipeline has not started")
        if generation != self._generation:
            return False
        self._webrtc.emit("add-ice-candidate", mline, candidate)
        return True

    def stop(self) -> None:
        if self._gst is None:
            self._active = False
            return
        _glib_main_context.call(self._stop_on_context)

    def _stop_on_context(self) -> None:
        self._active = False
        self._generation += 1
        self._teardown_on_context()

    def _teardown_on_context(self) -> None:
        pipeline = self._pipeline
        bus = self._bus
        handlers = self._signal_handlers
        self._pipeline = None
        self._webrtc = None
        self._bus = None
        self._signal_handlers = []
        for source, handler in handlers:
            try:
                source.disconnect(handler)
            except (TypeError, ValueError):
                pass
        if bus is not None:
            bus.remove_signal_watch()
        if pipeline is not None:
            pipeline.set_state(self._gst.State.NULL)
