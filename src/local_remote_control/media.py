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
        self._loop = None
        self._thread = None

    def ensure(self, glib) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            loop = glib.MainLoop()
            thread = self._thread_factory(
                target=loop.run,
                name="local-remote-control-glib",
                daemon=True,
            )
            self._loop = loop
            self._thread = thread
            thread.start()


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
        f"{encoder.pipeline_fragment} ! h264parse config-interval=-1 ! "
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
        on_offer: Callable[[str], None],
        on_ice: Callable[[int, str], None],
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
        self._pipeline = None
        self._webrtc = None

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
        description = _pipeline_description(self.encoder, self._display, self._fps)
        self._pipeline = Gst.parse_launch(description)
        self._webrtc = self._pipeline.get_by_name("sendrecv")
        self._webrtc.connect("on-negotiation-needed", self._create_offer)
        self._webrtc.connect("on-ice-candidate", lambda _, index, candidate: self._on_ice(index, candidate))
        bus = self._pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message::error", self._handle_error)
        self._pipeline.set_state(Gst.State.PLAYING)

    def _handle_error(self, _, message) -> None:
        error = message.parse_error()[0].message
        if self._fallback is not None and not self._fallback_used:
            self._fallback_used = True
            failed = self.encoder.name
            self.stop()
            self.encoder = self._fallback
            self._on_error(f"encoder {failed} falhou; alternando para {self.encoder.name}")
            self.start()
            return
        self._on_error(error)

    def _create_offer(self, element) -> None:
        from gi.repository import Gst, GstWebRTC
        promise = Gst.Promise.new_with_change_func(self._offer_created, element, None)
        element.emit("create-offer", None, promise)

    def _offer_created(self, promise, element, _) -> None:
        from gi.repository import Gst, GstWebRTC
        _complete_offer(promise, element, Gst.Promise.new(), self._on_offer)

    def set_remote_answer(self, sdp: str) -> None:
        if self._webrtc is None:
            raise MediaUnavailable("media pipeline has not started")
        from gi.repository import Gst, GstSdp, GstWebRTC
        result, message = GstSdp.SDPMessage.new()
        if GstSdp.sdp_message_parse_buffer(sdp.encode(), message) != GstSdp.SDPResult.OK:
            raise MediaUnavailable("invalid SDP answer")
        answer = GstWebRTC.WebRTCSessionDescription.new(GstWebRTC.WebRTCSDPType.ANSWER, message)
        self._webrtc.emit("set-remote-description", answer, Gst.Promise.new())

    def add_ice(self, candidate: str, mline: int) -> None:
        if self._webrtc is None:
            raise MediaUnavailable("media pipeline has not started")
        self._webrtc.emit("add-ice-candidate", mline, candidate)

    def stop(self) -> None:
        if self._pipeline is not None:
            from gi.repository import Gst
            self._pipeline.set_state(Gst.State.NULL)
        self._pipeline = self._webrtc = None
