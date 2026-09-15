export class VideoNegotiator {
  constructor({ createPeer, send, onTrack, onError = () => {} }) {
    this.createPeer = createPeer;
    this.send = send;
    this.onTrack = onTrack;
    this.onError = onError;
    this.peer = null;
    this.generation = null;
    this.queue = Promise.resolve();
  }

  handle(message) {
    this.queue = this.queue
      .then(() => this.apply(message))
      .catch((error) => this.onError(error));
    return this.queue;
  }

  async apply(message) {
    if (!Number.isInteger(message.negotiation)) return;
    if (message.type === 'offer') {
      await this.replacePeer(message.negotiation, message.sdp);
    } else if (message.type === 'ice' && message.negotiation === this.generation) {
      await this.peer?.addIceCandidate({
        candidate: message.candidate,
        sdpMLineIndex: message.mline,
      });
    }
  }

  async replacePeer(generation, sdp) {
    this.peer?.close();
    const peer = this.createPeer();
    this.peer = peer;
    this.generation = generation;
    peer.addEventListener('track', this.onTrack);
    peer.addEventListener('icecandidate', (event) => {
      if (!event.candidate || this.peer !== peer || this.generation !== generation) return;
      this.send({
        type: 'ice',
        negotiation: generation,
        candidate: event.candidate.candidate,
        mline: event.candidate.sdpMLineIndex,
      });
    });
    await peer.setRemoteDescription({ type: 'offer', sdp });
    const answer = await peer.createAnswer();
    await peer.setLocalDescription(answer);
    if (this.peer === peer && this.generation === generation) {
      this.send({ type: 'answer', negotiation: generation, sdp: answer.sdp });
    }
  }

  close() {
    this.peer?.close();
    this.peer = null;
    this.generation = null;
  }
}
