import test from 'node:test';
import assert from 'node:assert/strict';
import { keyMessage, pointerMessage, socketUrl } from '../src/local_remote_control/static/protocol.js';

test('normalizes pointer coordinates to the displayed video box', () => {
  const message = pointerMessage({ clientX: 150, clientY: 75 }, { left: 100, top: 50, width: 200, height: 100 });
  assert.deepEqual(message, { type: 'move', x: 0.25, y: 0.25 });
});

test('encodes only supported keyboard modifier names', () => {
  const message = keyMessage({ code: 'KeyA', type: 'keydown', ctrlKey: true, altKey: false, shiftKey: true, metaKey: false });
  assert.deepEqual(message, { type: 'key', code: 'KeyA', pressed: true, modifiers: ['Control', 'Shift'] });
});

test('creates a TLS websocket URL on the current host', () => {
  assert.equal(socketUrl('/ws/control', 'lease value', { protocol: 'https:', host: 'room.local:8443' }), 'wss://room.local:8443/ws/control?lease=lease%20value');
});
