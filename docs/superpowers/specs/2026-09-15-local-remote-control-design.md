# Local Remote Control — Design

## Objective

Build a purpose-made remote-control application for one Ubuntu notebook on a trusted local network. A second notebook connects with a modern browser and can view and control the Ubuntu desktop, use a terminal as the logged-in user, and exchange text through the clipboard. The Ubuntu host starts the application automatically after its existing automatic graphical login.

## Scope

The first release includes:

- one authenticated controlling browser at a time;
- low-latency desktop video over WebRTC;
- remote mouse, keyboard, and text input;
- a browser terminal backed by a local pseudo-terminal;
- bidirectional text clipboard synchronization;
- HTTPS, password authentication, session expiry, and login throttling;
- automatic selection of a hardware video encoder with a software fallback;
- an installer for Ubuntu and a systemd user service;
- automatic detection of Wayland and an opt-in switch to Xorg for unattended control;
- installation and operation instructions in the project README.

Audio, file transfer, internet traversal, multiple simultaneous controllers, and mobile-specific controls are excluded.

## Operating Assumptions

- The host is Ubuntu with an existing automatic login.
- The controller and host are on the same trusted LAN.
- The installer may use `sudo` to install OS packages and configure GDM/Xorg.
- The runtime service and terminal run as the graphical desktop user, never as root.
- Chrome and Firefox are the supported controller browsers.

## Architecture

The host application is an asynchronous Python service. Python coordinates the HTTP API, WebSockets, sessions, PTY, and native processes; performance-sensitive screen capture and H.264 encoding stay inside GStreamer.

The service contains focused modules:

1. **Configuration and security** load a root-owned or user-private configuration file, verify an Argon2 password hash, issue opaque in-memory sessions, enforce an Origin check, and throttle failed logins.
2. **Controller lease** grants exactly one browser control of video, input, clipboard, and terminal resources. A second authenticated browser receives a busy response until the lease expires or is released.
3. **WebRTC desktop** starts a GStreamer pipeline using X11 capture, an available H.264 encoder, and `webrtcbin`. It exchanges SDP and ICE over an authenticated signaling WebSocket. A data channel carries latency-sensitive input events.
4. **Input adapter** validates bounded input messages and injects mouse and keyboard events into the active X11 display through XTest-compatible tools. Text paste uses the clipboard rather than synthesizing arbitrary shell commands.
5. **Terminal manager** creates one PTY under the service user, relays bytes over an authenticated WebSocket, accepts resize messages, and terminates the child process when its lease closes.
6. **Clipboard bridge** observes X11 CLIPBOARD changes, applies size limits, and relays text changes while using revision identifiers to prevent feedback loops.
7. **Static web client** supplies login, connection state, a responsive remote canvas/video, a collapsible xterm.js terminal, explicit clipboard controls, and keyboard-capture escape controls.

## Data Flow

After HTTPS login, the browser requests the controller lease. The service creates a per-connection nonce and opens the signaling channel. GStreamer captures the X11 display, selects the configured encoder, and sends H.264 RTP through WebRTC. Input data-channel messages return directly to the host and are validated before injection.

Terminal data uses a separate WebSocket so terminal backpressure or a large command result cannot delay input. Clipboard text uses another small authenticated WebSocket message stream. Closing the page, losing heartbeats, logging out, or exceeding the idle timeout revokes the lease and closes all associated resources.

## Video and Latency Strategy

The installer probes GStreamer encoders in this order when present and usable: NVIDIA NVENC, VA-API, then x264 software encoding. The chosen pipeline uses no B-frames, a short keyframe interval, a small jitter buffer, and zerolatency tuning. The browser and service periodically exchange lightweight quality telemetry. The first release supports a configurable frame rate and bitrate, defaulting to 30 FPS and a LAN-friendly bitrate; resolution follows the host display.

No TURN server is used because the peers are on one LAN. ICE host candidates are sufficient. Video is never proxied through an external service.

## Security Model

- The installer prompts interactively for an application-specific password and stores only an Argon2id hash in a mode-`0600` environment file.
- A self-signed local TLS certificate is generated during installation. The README explains the one-time browser certificate warning.
- Authentication cookies are `Secure`, `HttpOnly`, and `SameSite=Strict`; mutating HTTP requests require a CSRF token.
- WebSockets validate both the authenticated session and the request Origin.
- Five failed logins trigger exponential per-address backoff.
- Sessions expire after inactivity and are lost on service restart by design.
- The listener binds to a configured address and the installer limits the application port to the detected LAN subnet when UFW is active.
- Terminal access is intentionally powerful, but it has exactly the privileges of the logged-in desktop user.
- Input payloads, clipboard sizes, terminal frame sizes, and WebSocket message sizes have explicit limits.

## Startup and Installation

An idempotent installer:

1. verifies Ubuntu and required commands;
2. installs Python, GStreamer, X11 input/clipboard tools, and encoder packages through APT;
3. creates a local virtual environment and installs pinned Python dependencies;
4. builds or installs vendored browser assets without requiring Node.js at runtime;
5. prompts for password and port, then generates the private configuration and TLS certificate;
6. detects the active session type and, with confirmation, configures GDM to use Xorg when necessary;
7. installs and enables a systemd user unit associated with the graphical session;
8. optionally adds a subnet-scoped UFW rule;
9. performs a health check and prints the LAN URL.

Uninstallation disables the user service and removes installed application configuration, but does not remove shared APT packages or user data without explicit confirmation.

## Error Handling and Recovery

Startup validates configuration, display access, required GStreamer plugins, and certificate files before accepting controller leases. The health endpoint reports coarse subsystem status without exposing secrets. Runtime failures are logged to the systemd journal with structured, redacted messages.

If hardware encoding fails, the desktop module retries once with x264. A broken WebRTC or WebSocket connection revokes the controller lease and permits reconnection after a short cleanup window. PTY children receive a graceful termination signal followed by a bounded forced shutdown. Clipboard failures disable clipboard synchronization without taking down video or terminal access.

## User Interface

The authenticated page prioritizes the remote video. A compact top bar shows connection quality, fullscreen, clipboard synchronization, terminal visibility, and disconnect controls. The terminal opens in a resizable lower panel. Clicking the video captures keyboard input; `Ctrl+Alt+Shift` releases it locally. Browser-reserved shortcuts that cannot be captured are documented.

Connection, authentication, busy-controller, encoder fallback, and clipboard-permission states use direct Portuguese messages and actionable recovery instructions.

## Testing

- Unit tests cover configuration validation, password verification, throttling, sessions, lease transitions, input validation, clipboard loop prevention, PTY message parsing, and encoder selection.
- Async integration tests exercise login, CSRF, Origin enforcement, controller exclusivity, WebSocket cleanup, and health responses.
- Browser tests cover login, connection lifecycle, keyboard release, terminal resizing, and clipboard controls with mocked media/signaling boundaries.
- Installer checks run against temporary filesystem roots and mocked system commands.
- A manual Ubuntu acceptance checklist verifies boot-to-service startup, Xorg migration, Chrome and Firefox, hardware/software encoding, reconnect behavior, and LAN-only reachability.

## Delivery Boundaries

The repository ships source, tests, static assets, installer/uninstaller scripts, systemd unit templates, and operator documentation. It does not modify the host until the user runs the installer. The README distinguishes development setup from production installation and includes troubleshooting commands for service logs, display access, ports, certificates, and encoder selection.
