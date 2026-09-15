from local_remote_control.input import InputAdapter
from local_remote_control.protocol import KeyEvent, MouseButton, MouseMove, MouseWheel, TextInput


class RecordingRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    async def __call__(self, *args: str) -> None:
        self.calls.append(args)


async def test_scales_pointer_and_translates_controls() -> None:
    runner = RecordingRunner()
    pasted: list[str] = []
    adapter = InputAdapter(runner, lambda: (1920, 1080), pasted.append)

    await adapter.apply(MouseMove(0.5, 1.0))
    await adapter.apply(MouseButton(1, True))
    await adapter.apply(MouseWheel(0, -2))
    await adapter.apply(KeyEvent("KeyA", True, ("Control",)))
    await adapter.apply(TextInput("hello; $(unsafe)"))

    assert runner.calls == [
        ("xdotool", "mousemove", "960", "1079"),
        ("xdotool", "mousedown", "1"),
        ("xdotool", "click", "5", "click", "5"),
        ("xdotool", "keydown", "ctrl+a"),
    ]
    assert pasted == ["hello; $(unsafe)"]
