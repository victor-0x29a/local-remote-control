# Local Remote Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an installable Ubuntu service that exposes one authenticated, low-latency browser session for desktop control, terminal access, and text clipboard synchronization on the LAN.

**Architecture:** An aiohttp service owns authentication, the exclusive controller lease, WebSocket protocols, and PTY lifecycle. Native GStreamer captures X11 and sends H.264 through WebRTC; small adapters isolate GStreamer, X11 input, and clipboard operations so core behavior remains unit-testable without a graphical session.

**Tech Stack:** Python 3.10+, aiohttp, argon2-cffi, PyGObject/GStreamer 1.20+, pytest, vanilla ES modules, xterm.js, systemd, Bash installer.

**Spec:** `docs/superpowers/specs/2026-09-15-local-remote-control-design.md`

## Global Constraints

- Support Ubuntu with an existing automatic graphical login and switch Wayland to Xorg with explicit installer confirmation.
- Run the service and terminal as the graphical desktop user, never as root.
- Permit exactly one authenticated controller at a time.
- Keep all media and control traffic on the LAN; do not use TURN or external services.
- Include screen, keyboard, mouse, terminal, and bidirectional text clipboard; exclude audio and file transfer.
- Store only an Argon2id password hash and use HTTPS, secure cookies, CSRF protection, Origin checks, session expiry, and login throttling.
- Prefer NVENC, then VA-API, then x264 zerolatency, with runtime fallback to x264.
- Make each independently meaningful change a micro-commit.

---

### Task 1: Python Package and Validated Configuration

**Files:**
- Create: `pyproject.toml`
- Create: `src/local_remote_control/__init__.py`
- Create: `src/local_remote_control/config.py`
- Create: `tests/test_config.py`

**Interfaces:**
- Produces: `Settings.load(path: Path) -> Settings`; immutable fields `bind_host`, `port`, `public_host`, `password_hash`, `certificate`, `private_key`, `session_idle_seconds`, `max_clipboard_bytes`, `display`, `shell`.

- [ ] **Step 1: Add packaging metadata and test dependencies**

Define Python `>=3.10`, runtime dependencies `aiohttp>=3.9,<4`, `argon2-cffi>=23,<26`, and optional test dependencies `pytest>=8,<9`, `pytest-asyncio>=0.23,<1`. Configure pytest with `pythonpath = ["src"]` and asyncio mode `auto`.

- [ ] **Step 2: Commit packaging metadata**

```bash
git add pyproject.toml src/local_remote_control/__init__.py && git commit -m "build: initialize Python package"
```

- [ ] **Step 3: Write failing configuration tests**

```python
def test_loads_private_environment_file(tmp_path):
    config = write_config(tmp_path, mode=0o600)
    settings = Settings.load(config)
    assert settings.port == 8443
    assert settings.display == ":0"

def test_rejects_group_readable_secrets(tmp_path):
    config = write_config(tmp_path, mode=0o640)
    with pytest.raises(ConfigError, match="0600"):
        Settings.load(config)
```

- [ ] **Step 4: Commit the red tests**

```bash
git add tests/test_config.py && git commit -m "test: specify secure configuration loading"
```

- [ ] **Step 5: Implement strict configuration parsing**

Use a frozen dataclass, parse only documented `KEY=VALUE` lines, reject missing fields, non-numeric/out-of-range ports, public hosts containing schemes or paths, and files whose group/other permission bits are nonzero.

- [ ] **Step 6: Verify and commit**

Run `pytest tests/test_config.py -q`; expect all tests to pass.

```bash
git add src/local_remote_control/config.py && git commit -m "feat: load validated private configuration"
```

### Task 2: Password Throttling and Browser Sessions

**Files:**
- Create: `src/local_remote_control/security.py`
- Create: `tests/test_security.py`

**Interfaces:**
- Consumes: `Settings.password_hash`, `Settings.session_idle_seconds`.
- Produces: `AuthManager.verify_password(ip: str, password: str, now: float) -> bool`, `create_session(now: float) -> Session`, `authenticate(token: str, now: float) -> Session | None`, `revoke(token: str) -> None`; `Session(token, csrf, created_at, last_seen)`.

- [ ] **Step 1: Specify Argon2 verification, five-attempt backoff, expiry, and revocation**

Tests use an injected `PasswordHasher`; assert invalid passwords increment per-IP state, the sixth immediate attempt is denied without hashing, successful login resets failures, idle sessions expire, CSRF tokens differ from cookie tokens, and revoked tokens cannot authenticate.

- [ ] **Step 2: Commit the red security tests**

```bash
git add tests/test_security.py && git commit -m "test: define authentication and session rules"
```

- [ ] **Step 3: Implement in-memory security state**

Use `secrets.token_urlsafe(32)`, `hmac.compare_digest` where tokens are compared, monotonic timestamps supplied by callers, a maximum of 128 remembered IP records, and exponential delays capped at 60 seconds.

- [ ] **Step 4: Verify and commit**

Run `pytest tests/test_security.py -q`; expect all tests to pass.

```bash
git add src/local_remote_control/security.py && git commit -m "feat: secure login and browser sessions"
```

### Task 3: Exclusive Controller Lease

**Files:**
- Create: `src/local_remote_control/lease.py`
- Create: `tests/test_lease.py`

**Interfaces:**
- Produces: async `ControllerLease.acquire(session_token: str) -> LeaseHandle | None`, `heartbeat(handle_id: str) -> bool`, `release(handle_id: str) -> None`, `reap(now: float) -> bool`; `LeaseHandle(id, session_token)`.

- [ ] **Step 1: Write concurrency and stale-lease tests**

Assert two simultaneous acquisitions produce exactly one handle, only the owner can release, heartbeats refresh expiry, and a stale controller can be reaped and replaced.

- [ ] **Step 2: Commit the red lease tests**

```bash
git add tests/test_lease.py && git commit -m "test: specify exclusive controller lease"
```

- [ ] **Step 3: Implement the lease with an `asyncio.Lock`**

Generate opaque handle IDs, keep one active record, default heartbeat timeout to 15 seconds, and never expose session tokens in logging representations.

- [ ] **Step 4: Verify and commit**

Run `pytest tests/test_lease.py -q`; expect all tests to pass.

```bash
git add src/local_remote_control/lease.py && git commit -m "feat: enforce one active controller"
```

### Task 4: Bounded Control Protocol

**Files:**
- Create: `src/local_remote_control/protocol.py`
- Create: `src/local_remote_control/input.py`
- Create: `tests/test_protocol.py`
- Create: `tests/test_input.py`

**Interfaces:**
- Produces: `parse_control_message(raw: str) -> ControlEvent`; event dataclasses `MouseMove(x, y)`, `MouseButton(button, pressed)`, `MouseWheel(dx, dy)`, `KeyEvent(code, pressed, modifiers)`, `TextInput(text)`, `Heartbeat()`; `InputAdapter.apply(event) -> None`.

- [ ] **Step 1: Test the JSON protocol and hard limits**

Cover normalized mouse coordinates in `[0,1]`, buttons 1–5, wheel deltas capped at 20, allowlisted browser key codes, text capped at 4096 UTF-8 bytes, heartbeat, malformed JSON, unknown properties, and messages over 8192 bytes.

- [ ] **Step 2: Commit protocol tests**

```bash
git add tests/test_protocol.py && git commit -m "test: define bounded control messages"
```

- [ ] **Step 3: Implement strict decoding**

Use dataclasses and explicit field sets for each message type; reject booleans where numeric values are expected and reject non-finite floats.

- [ ] **Step 4: Verify and commit protocol**

Run `pytest tests/test_protocol.py -q`; expect all tests to pass.

```bash
git add src/local_remote_control/protocol.py && git commit -m "feat: validate remote input protocol"
```

- [ ] **Step 5: Test X11 command translation with a fake runner**

Assert coordinates scale to current screen bounds, key codes map to X11 key names, dangerous unmapped keys are ignored, and text is sent through the clipboard adapter rather than interpolated into a shell command.

- [ ] **Step 6: Implement argument-vector-only X11 input commands**

Invoke `xdotool` with `create_subprocess_exec`, never a shell; serialize events with an async lock and inject display/environment explicitly.

- [ ] **Step 7: Verify and commit input adapter**

Run `pytest tests/test_input.py -q`; expect all tests to pass.

```bash
git add tests/test_input.py src/local_remote_control/input.py && git commit -m "feat: inject validated X11 input"
```

### Task 5: Terminal Protocol and PTY Lifecycle

**Files:**
- Create: `src/local_remote_control/terminal.py`
- Create: `tests/test_terminal.py`

**Interfaces:**
- Produces: `parse_terminal_message(raw: bytes | str) -> TerminalInput | TerminalResize`; async `PtySession.start(shell, env)`, `write(data)`, `resize(rows, cols)`, `read_chunks()`, `close()`.

- [ ] **Step 1: Test terminal frames and lifecycle through an injected PTY backend**

Cover binary input capped at 64 KiB, resize bounds of 2–300 rows and 2–500 columns, environment allowlisting, EOF, graceful close, and forced close after a one-second timeout.

- [ ] **Step 2: Commit terminal tests**

```bash
git add tests/test_terminal.py && git commit -m "test: define terminal protocol and lifecycle"
```

- [ ] **Step 3: Implement PTY management**

Use `pty.openpty`, `fcntl.ioctl(TIOCSWINSZ)`, `asyncio.create_subprocess_exec(shell, "-l", ...)`, nonblocking reads, and process-group termination. Preserve `HOME`, `USER`, `LOGNAME`, `PATH`, `SHELL`, `TERM`, `LANG`, and `DISPLAY` only.

- [ ] **Step 4: Verify and commit**

Run `pytest tests/test_terminal.py -q`; expect all tests to pass.

```bash
git add src/local_remote_control/terminal.py && git commit -m "feat: provide logged-in user PTY sessions"
```

### Task 6: Text Clipboard Bridge

**Files:**
- Create: `src/local_remote_control/clipboard.py`
- Create: `tests/test_clipboard.py`

**Interfaces:**
- Produces: `ClipboardUpdate(revision, text, source)`; async `ClipboardBridge.read()`, `write(text, remote_revision)`, `watch(callback)`, `close()`.

- [ ] **Step 1: Test UTF-8 bounds and feedback-loop prevention**

With a fake `xclip` runner, assert unchanged content is suppressed, locally changed text emits a monotonic revision, echoed remote content is suppressed once, binary/invalid UTF-8 content is rejected, and oversized text yields `ClipboardTooLarge`.

- [ ] **Step 2: Commit clipboard tests**

```bash
git add tests/test_clipboard.py && git commit -m "test: specify text clipboard synchronization"
```

- [ ] **Step 3: Implement polling clipboard adapter**

Use `xclip -selection clipboard` with argument vectors and byte pipes, poll at 250 ms only while a controller is active, cap reads before decoding, and redact clipboard content from logs.

- [ ] **Step 4: Verify and commit**

Run `pytest tests/test_clipboard.py -q`; expect all tests to pass.

```bash
git add src/local_remote_control/clipboard.py && git commit -m "feat: synchronize bounded text clipboard"
```

### Task 7: Encoder Probing and WebRTC Pipeline

**Files:**
- Create: `src/local_remote_control/media.py`
- Create: `tests/test_media.py`

**Interfaces:**
- Produces: `Encoder(name, pipeline_fragment, hardware)`; `select_encoder(available: set[str]) -> Encoder`; `WebRtcDesktop.start(encoder, offer_callback, ice_callback)`, `set_remote_answer(sdp)`, `add_ice(candidate, mline)`, `stop()`.

- [ ] **Step 1: Test deterministic encoder order and safe pipeline creation**

Assert `nvh264enc` wins over `vah264enc`, both win over `x264enc`, missing all encoders raises `MediaUnavailable`, pipeline parameters are numeric/range-validated, and SDP/ICE calls before startup fail cleanly.

- [ ] **Step 2: Commit media tests**

```bash
git add tests/test_media.py && git commit -m "test: define encoder selection and media lifecycle"
```

- [ ] **Step 3: Implement GStreamer behind lazy imports**

Build `ximagesrc use-damage=true show-pointer=true ! videoconvert ! queue max-size-buffers=1 leaky=downstream ! <encoder> ! h264parse config-interval=-1 ! rtph264pay pt=96 ! webrtcbin`. Import `gi` only in `start` so unit tests work without a display. Route GStreamer bus errors to an injected callback and retry hardware failure once with x264.

- [ ] **Step 4: Verify and commit**

Run `pytest tests/test_media.py -q`; expect all tests to pass.

```bash
git add src/local_remote_control/media.py && git commit -m "feat: stream X11 desktop through WebRTC"
```

### Task 8: Authenticated HTTP and WebSocket Application

**Files:**
- Create: `src/local_remote_control/web.py`
- Create: `src/local_remote_control/main.py`
- Create: `tests/test_web.py`

**Interfaces:**
- Consumes: `Settings`, `AuthManager`, `ControllerLease`, `InputAdapter`, `PtySession`, `ClipboardBridge`, `WebRtcDesktop`.
- Produces: `create_app(dependencies) -> web.Application`; routes `/`, `/api/login`, `/api/logout`, `/api/status`, `/api/lease`, `/ws/control`, `/ws/signal`, `/ws/terminal`, `/ws/clipboard`, `/healthz`.

- [ ] **Step 1: Test login cookies, CSRF, Origin, health privacy, and lease conflicts**

Use aiohttp's test client. Assert cookies have Secure/HttpOnly/SameSite flags; POSTs reject missing CSRF; WebSockets reject foreign Origins and missing sessions; the second lease receives HTTP 409; health reports booleans and encoder name but no paths, hashes, tokens, or environment.

- [ ] **Step 2: Commit HTTP security tests**

```bash
git add tests/test_web.py && git commit -m "test: define secure HTTP boundaries"
```

- [ ] **Step 3: Implement routes and cleanup ownership**

Set an 8 KiB JSON limit and 64 KiB binary limit, create all controller resources only after lease acquisition, send heartbeats every five seconds, and close media/PTY/clipboard then release the lease in `finally` blocks.

- [ ] **Step 4: Verify and commit application routes**

Run `pytest tests/test_web.py -q`; expect all tests to pass.

```bash
git add src/local_remote_control/web.py && git commit -m "feat: expose authenticated control gateway"
```

- [ ] **Step 5: Add TLS entry point and graceful shutdown**

Load only TLS 1.2+, bind `Settings.bind_host:port`, handle SIGINT/SIGTERM, periodically reap sessions/leases, and expose `python -m local_remote_control.main --config PATH`.

- [ ] **Step 6: Test CLI parsing and commit**

Run `python -m local_remote_control.main --help` and `pytest -q`; expect help exit 0 and all tests passing.

```bash
git add src/local_remote_control/main.py pyproject.toml && git commit -m "feat: run HTTPS control service"
```

### Task 9: Browser Client

**Files:**
- Create: `src/local_remote_control/static/index.html`
- Create: `src/local_remote_control/static/styles.css`
- Create: `src/local_remote_control/static/app.js`
- Create: `tests/test_static.py`

**Interfaces:**
- Consumes: the routes and protocols from Tasks 4 and 8.
- Produces: browser login, WebRTC video, normalized pointer events, keyboard capture/release, clipboard actions, xterm.js terminal, reconnect and error states.

- [ ] **Step 1: Test the static security contract**

Parse the HTML and assert there are no remote scripts/styles, password autocomplete is current-password, the video is autoplay/playsinline, status is an ARIA live region, and all controls have accessible names.

- [ ] **Step 2: Commit static contract tests**

```bash
git add tests/test_static.py && git commit -m "test: define browser client contract"
```

- [ ] **Step 3: Build the responsive shell and login state**

Use semantic HTML and a dark, high-contrast desktop layout. Fetch `/api/login`, retain CSRF only in memory, show actionable Portuguese errors, and provide connect/disconnect/fullscreen/terminal/clipboard buttons.

- [ ] **Step 4: Commit visual shell**

```bash
git add src/local_remote_control/static/index.html src/local_remote_control/static/styles.css && git commit -m "feat: add responsive remote workspace"
```

- [ ] **Step 5: Implement WebRTC and input capture**

Use `RTCPeerConnection` without public ICE servers, exchange SDP/ICE at `/ws/signal`, send coalesced pointer moves through `/ws/control`, prevent defaults only while captured, and release capture on `Ctrl+Alt+Shift`.

- [ ] **Step 6: Commit browser control**

```bash
git add src/local_remote_control/static/app.js && git commit -m "feat: control desktop from the browser"
```

- [ ] **Step 7: Vendor xterm.js and integrate terminal/clipboard**

Place pinned minified xterm.js assets under `static/vendor/` with license notices. Relay terminal bytes with `TextEncoder/TextDecoder`, debounce resize, use the browser Clipboard API only from user gestures, and provide text-area fallback when permission is denied.

- [ ] **Step 8: Verify and commit integrations**

Run `pytest tests/test_static.py -q`; expect all tests to pass.

```bash
git add src/local_remote_control/static tests/test_static.py && git commit -m "feat: add web terminal and clipboard controls"
```

### Task 10: Installer, Service, and Host Diagnostics

**Files:**
- Create: `packaging/local-remote-control.service`
- Create: `scripts/install.sh`
- Create: `scripts/uninstall.sh`
- Create: `scripts/diagnose.sh`
- Create: `tests/test_packaging.py`

**Interfaces:**
- Installer flags: `--port`, `--bind`, `--yes-xorg`, `--skip-ufw`; environment override `LRC_ROOT` only for tests.
- Service invokes `%h/.local/share/local-remote-control/venv/bin/local-remote-control --config %h/.config/local-remote-control/config.env` after `graphical-session.target`.

- [ ] **Step 1: Test unit hardening and installer idempotence statically**

Assert `NoNewPrivileges=true`, `PrivateTmp=true`, restart backoff, graphical target ordering, no root service user, quoted paths, Ubuntu guard, password read with `read -s`, `umask 077`, Argon2 hashing via the venv, certificate generation, Xorg confirmation, UFW subnet scope, `systemctl --user enable --now`, and repeat-safe directory creation.

- [ ] **Step 2: Commit packaging tests**

```bash
git add tests/test_packaging.py && git commit -m "test: define safe Ubuntu installation"
```

- [ ] **Step 3: Add the systemd user unit**

Set environment for `DISPLAY=:0` and `XAUTHORITY=%h/.Xauthority`, wait for the display, restart on failure, and apply hardening that does not block PTY, X11, or GStreamer device access.

- [ ] **Step 4: Commit service definition**

```bash
git add packaging/local-remote-control.service && git commit -m "feat: start control service with desktop login"
```

- [ ] **Step 5: Implement the Ubuntu installer**

Install exact apt capability groups, copy source to the user data directory, create the venv, hash the prompted password, generate a 10-year local certificate with host IP SAN, detect session/GDM configuration, enable lingering only when necessary, optionally add UFW rule from `ip route`, start the service, and print URL plus journal command.

- [ ] **Step 6: Commit installer**

```bash
git add scripts/install.sh && git commit -m "feat: install and configure Ubuntu host"
```

- [ ] **Step 7: Add conservative uninstall and diagnostics**

Uninstall disables service and removes only application-owned runtime/config files after confirmation. Diagnostics prints versions, session type, encoder availability, port/listener, service status, recent redacted logs, and never prints the password hash or private key.

- [ ] **Step 8: Verify and commit lifecycle tools**

Run `pytest tests/test_packaging.py -q` and `bash -n scripts/*.sh`; expect all checks to pass.

```bash
git add scripts/uninstall.sh scripts/diagnose.sh && git commit -m "feat: add host cleanup and diagnostics"
```

### Task 11: Operator Documentation and Final Verification

**Files:**
- Create: `README.md`
- Create: `docs/manual-acceptance.md`
- Create: `LICENSE`

**Interfaces:**
- Documents the complete room-notebook installation and bedroom-browser connection workflows.

- [ ] **Step 1: Write the Ubuntu installation README**

Include prerequisites, cloning/copying, `chmod +x scripts/*.sh`, `./scripts/install.sh`, password prompt, optional Xorg reboot, one-time certificate warning, printed LAN URL, browser login, keyboard release shortcut, clipboard user gestures, terminal warning, start/stop/restart/status/journal commands, upgrades, diagnostics, uninstall, firewall behavior, and explicit statement that the app must not be port-forwarded.

- [ ] **Step 2: Commit primary documentation**

```bash
git add README.md && git commit -m "docs: explain room notebook installation"
```

- [ ] **Step 3: Add manual acceptance matrix and license**

Cover fresh Ubuntu installation, reboot/autostart, Xorg migration, Chrome, Firefox, NVENC/VA-API/x264, reconnect, second-controller rejection, clipboard both directions, terminal resize/exit, authentication throttling, LAN access, and WAN non-exposure. Use the MIT license.

- [ ] **Step 4: Commit acceptance docs and license separately**

```bash
git add docs/manual-acceptance.md && git commit -m "docs: add Ubuntu acceptance checklist"
git add LICENSE && git commit -m "docs: license project under MIT"
```

- [ ] **Step 5: Run the complete verification suite**

Run:

```bash
python -m compileall -q src
pytest -q
bash -n scripts/*.sh
git status --short
```

Expected: compilation succeeds, all automated tests pass, shell syntax checks pass, and the worktree contains no uncommitted project changes.
