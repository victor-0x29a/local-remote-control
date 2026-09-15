import assert from 'node:assert/strict';
import test from 'node:test';

import { VideoNegotiator } from '../src/local_remote_control/static/video-signaling.js';


test('replaces the peer and ignores stale negotiation signaling', async () => {
  const peers = [];
  const sent = [];
  const negotiator = new VideoNegotiator({
    createPeer: () => peers.push(new FakePeer()) && peers.at(-1),
    send: (message) => sent.push(message),
    onTrack: () => {},
  });

  await negotiator.handle({ type: 'offer', negotiation: 1, sdp: 'offer-one' });
  await negotiator.handle({ type: 'offer', negotiation: 2, sdp: 'offer-two' });
  await negotiator.handle({ type: 'ice', negotiation: 1, mline: 0, candidate: 'stale' });
  await negotiator.handle({ type: 'ice', negotiation: 2, mline: 0, candidate: 'current' });
  peers[0].emitIce('late-local-candidate');
  peers[1].emitIce('current-local-candidate');

  assert.equal(peers[0].closed, true);
  assert.deepEqual(peers[0].candidates, []);
  assert.deepEqual(peers[1].candidates, [{ candidate: 'current', sdpMLineIndex: 0 }]);
  assert.deepEqual(sent, [
    { type: 'answer', negotiation: 1, sdp: 'answer:offer-one' },
    { type: 'answer', negotiation: 2, sdp: 'answer:offer-two' },
    { type: 'ice', negotiation: 2, candidate: 'current-local-candidate', mline: 0 },
  ]);
});


class FakePeer {
  constructor() {
    this.listeners = new Map();
    this.candidates = [];
    this.closed = false;
  }

  addEventListener(name, callback) {
    this.listeners.set(name, callback);
  }

  async setRemoteDescription(description) {
    this.remote = description;
  }

  async createAnswer() {
    return { type: 'answer', sdp: `answer:${this.remote.sdp}` };
  }

  async setLocalDescription(description) {
    this.local = description;
  }

  async addIceCandidate(candidate) {
    this.candidates.push(candidate);
  }

  close() {
    this.closed = true;
  }

  emitIce(candidate) {
    this.listeners.get('icecandidate')?.({
      candidate: { candidate, sdpMLineIndex: 0 },
    });
  }
}
