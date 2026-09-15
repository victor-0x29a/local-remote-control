import { keyMessage, pointerMessage, socketUrl } from './protocol.js';

const loginView = document.querySelector('#login-view');
const workspace = document.querySelector('#workspace');
const loginForm = document.querySelector('#login-form');
const loginError = document.querySelector('#login-error');
const password = document.querySelector('#password');
const status = document.querySelector('#status');
const desktop = document.querySelector('#desktop');
const video = document.querySelector('#remote-video');
const emptyState = document.querySelector('#empty-state');
const terminalPanel = document.querySelector('#terminal-panel');
const clipboardFallback = document.querySelector('#clipboard-fallback');

let csrf = '';
let lease = '';
let controlSocket;
let signalSocket;
let terminalSocket;
let clipboardSocket;
let peer;
let terminal;
let keyboardCaptured = false;
let latestHostClipboard = '';
let pointerFrame = 0;
let pendingPointer;

loginForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  loginError.textContent = '';
  try {
    const response = await fetch('/api/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password: password.value }),
    });
    if (!response.ok) throw new Error(await response.text());
    csrf = (await response.json()).csrf;
    const acquired = await api('/api/lease', { method: 'POST' });
    lease = acquired.lease;
    loginView.hidden = true;
    workspace.hidden = false;
    await connect();
  } catch (error) {
    loginError.textContent = error.message || 'Não foi possível entrar.';
    password.select();
  }
});

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (options.method && options.method !== 'GET') headers.set('X-CSRF-Token', csrf);
  const response = await fetch(path, { ...options, headers });
  if (!response.ok) throw new Error(await response.text());
  return response.status === 204 ? null : response.json();
}

async function connect() {
  setStatus('Conectando ao notebook…');
  controlSocket = new WebSocket(socketUrl('/ws/control', lease));
  controlSocket.addEventListener('open', () => {
    setStatus('Conectado — clique na tela para controlar');
    setInterval(() => sendControl({ type: 'heartbeat' }), 5000);
  });
  controlSocket.addEventListener('close', () => setStatus('Controle desconectado. Recarregue para tentar novamente.', true));
  await connectVideo();
  connectClipboard();
}

async function connectVideo() {
  peer = new RTCPeerConnection({ iceServers: [], bundlePolicy: 'max-bundle' });
  peer.addEventListener('track', (event) => {
    video.srcObject = event.streams[0];
    emptyState.hidden = true;
  });
  signalSocket = new WebSocket(socketUrl('/ws/signal', lease));
  signalSocket.addEventListener('message', async (event) => {
    const message = JSON.parse(event.data);
    if (message.type === 'offer') {
      await peer.setRemoteDescription({ type: 'offer', sdp: message.sdp });
      const answer = await peer.createAnswer();
      await peer.setLocalDescription(answer);
      signalSocket.send(JSON.stringify({ type: 'answer', sdp: answer.sdp }));
    } else if (message.type === 'ice') {
      await peer.addIceCandidate({ candidate: message.candidate, sdpMLineIndex: message.mline });
    } else if (message.type === 'error') {
      setStatus(`Falha de vídeo: ${message.message}`, true);
    }
  });
  peer.addEventListener('icecandidate', (event) => {
    if (event.candidate && signalSocket.readyState === WebSocket.OPEN) {
      signalSocket.send(JSON.stringify({ type: 'ice', candidate: event.candidate.candidate, mline: event.candidate.sdpMLineIndex }));
    }
  });
}

function sendControl(message) {
  if (controlSocket?.readyState === WebSocket.OPEN) controlSocket.send(JSON.stringify(message));
}

desktop.addEventListener('click', () => {
  keyboardCaptured = true;
  desktop.focus();
});
desktop.addEventListener('mousemove', (event) => {
  pendingPointer = event;
  if (!pointerFrame) pointerFrame = requestAnimationFrame(() => {
    sendControl(pointerMessage(pendingPointer, video.getBoundingClientRect()));
    pointerFrame = 0;
  });
});
desktop.addEventListener('mousedown', (event) => { event.preventDefault(); sendControl({ type: 'button', button: event.button + 1, pressed: true }); });
desktop.addEventListener('mouseup', (event) => { event.preventDefault(); sendControl({ type: 'button', button: event.button + 1, pressed: false }); });
desktop.addEventListener('contextmenu', (event) => event.preventDefault());
desktop.addEventListener('wheel', (event) => {
  event.preventDefault();
  sendControl({ type: 'wheel', dx: Math.max(-20, Math.min(20, event.deltaX / 100)), dy: Math.max(-20, Math.min(20, event.deltaY / 100)) });
}, { passive: false });
window.addEventListener('keydown', captureKey, true);
window.addEventListener('keyup', captureKey, true);

function captureKey(event) {
  if (!keyboardCaptured) return;
  if (event.ctrlKey && event.altKey && event.shiftKey) {
    keyboardCaptured = false;
    desktop.blur();
    setStatus('Teclado liberado; clique na tela para recapturar');
    return;
  }
  if (document.activeElement?.closest?.('.xterm')) return;
  event.preventDefault();
  sendControl(keyMessage(event));
}

desktop.addEventListener('paste', (event) => {
  const text = event.clipboardData?.getData('text/plain');
  if (text) {
    event.preventDefault();
    sendControl({ type: 'text', text: text.slice(0, 4096) });
  }
});

function connectClipboard() {
  clipboardSocket = new WebSocket(socketUrl('/ws/clipboard', lease));
  clipboardSocket.addEventListener('message', (event) => {
    const message = JSON.parse(event.data);
    if (message.type === 'clipboard') {
      latestHostClipboard = message.text;
      setStatus('Texto copiado na sala — use o botão Colar para trazê-lo');
    }
  });
}

document.querySelector('#clipboard-button').addEventListener('click', async () => {
  try {
    if (latestHostClipboard) {
      await navigator.clipboard.writeText(latestHostClipboard);
      latestHostClipboard = '';
      setStatus('Texto da sala copiado para este notebook');
    } else {
      const text = await navigator.clipboard.readText();
      clipboardSocket.send(JSON.stringify({ type: 'clipboard', revision: crypto.randomUUID(), text }));
      setStatus('Clipboard enviado ao notebook da sala');
    }
  } catch {
    clipboardFallback.hidden = false;
    clipboardFallback.value = latestHostClipboard;
    clipboardFallback.focus();
    clipboardFallback.select();
    setStatus('O navegador bloqueou o clipboard automático; use a caixa de texto.', true);
  }
});

function openTerminal() {
  terminalPanel.hidden = false;
  if (!terminal && window.Terminal) {
    terminal = new window.Terminal({ cursorBlink: true, convertEol: true, theme: { background: '#081018', foreground: '#edf4ff' } });
    terminal.open(document.querySelector('#terminal'));
    terminalSocket = new WebSocket(socketUrl('/ws/terminal', lease));
    terminalSocket.binaryType = 'arraybuffer';
    terminalSocket.addEventListener('message', (event) => terminal.write(typeof event.data === 'string' ? event.data : new Uint8Array(event.data)));
    terminal.onResize(sendTerminalSize);
    terminal.onData((data) => terminalSocket.readyState === WebSocket.OPEN && terminalSocket.send(new TextEncoder().encode(data)));
    terminalSocket.addEventListener('open', () => { terminal.focus(); sendTerminalSize(); });
  }
}

function sendTerminalSize() {
  if (terminalSocket?.readyState === WebSocket.OPEN) terminalSocket.send(JSON.stringify({ type: 'resize', rows: terminal.rows, cols: terminal.cols }));
}

document.querySelector('#terminal-button').addEventListener('click', () => terminalPanel.hidden ? openTerminal() : terminalPanel.hidden = true);
document.querySelector('#terminal-close').addEventListener('click', () => terminalPanel.hidden = true);
document.querySelector('#fullscreen-button').addEventListener('click', () => document.fullscreenElement ? document.exitFullscreen() : workspace.requestFullscreen());
document.querySelector('#disconnect-button').addEventListener('click', disconnect);

async function disconnect() {
  try { await api(`/api/lease/${encodeURIComponent(lease)}`, { method: 'DELETE' }); } catch { /* best effort */ }
  [controlSocket, signalSocket, terminalSocket, clipboardSocket].forEach((socket) => socket?.close());
  peer?.close();
  location.reload();
}

function setStatus(message, failed = false) {
  status.textContent = message;
  status.style.color = failed ? 'var(--danger)' : '';
}
