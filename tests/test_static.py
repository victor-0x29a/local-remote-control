from html.parser import HTMLParser
from pathlib import Path


class Tags(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: list[tuple[str, dict[str, str | None]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append((tag, dict(attrs)))


def test_page_has_local_assets_and_accessible_remote_controls() -> None:
    html = Path("src/local_remote_control/static/index.html").read_text(encoding="utf-8")
    parser = Tags()
    parser.feed(html)
    assert "https://" not in html and "http://" not in html
    password = next(attrs for tag, attrs in parser.tags if tag == "input" and attrs.get("type") == "password")
    video = next(attrs for tag, attrs in parser.tags if tag == "video")
    status = next(attrs for tag, attrs in parser.tags if attrs.get("id") == "status")
    assert password["autocomplete"] == "current-password"
    assert "autoplay" in video and "playsinline" in video
    assert status["aria-live"] == "polite"
    assert all(attrs.get("aria-label") or attrs.get("title") or (tag != "button") for tag, attrs in parser.tags)


def test_browser_interface_uses_generic_remote_host_language() -> None:
    static_dir = Path("src/local_remote_control/static")
    interface = "\n".join(
        (static_dir / filename).read_text(encoding="utf-8")
        for filename in ("index.html", "app.js")
    ).lower()

    assert "sala" not in interface
    assert "quarto" not in interface


def test_terminal_exposes_clipboard_and_view_controls() -> None:
    html = Path("src/local_remote_control/static/index.html").read_text(encoding="utf-8")
    parser = Tags()
    parser.feed(html)
    button_ids = {
        attrs.get("id")
        for tag, attrs in parser.tags
        if tag == "button"
    }

    assert {
        "terminal-copy",
        "terminal-paste",
        "terminal-clear",
        "terminal-expand",
        "terminal-close",
    } <= button_ids
