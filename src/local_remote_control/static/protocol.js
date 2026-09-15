export function pointerMessage(event, rectangle) {
  const x = Math.max(0, Math.min(1, (event.clientX - rectangle.left) / rectangle.width));
  const y = Math.max(0, Math.min(1, (event.clientY - rectangle.top) / rectangle.height));
  return { type: 'move', x, y };
}

export function keyMessage(event) {
  const modifiers = [];
  if (event.altKey) modifiers.push('Alt');
  if (event.ctrlKey) modifiers.push('Control');
  if (event.metaKey) modifiers.push('Meta');
  if (event.shiftKey) modifiers.push('Shift');
  return { type: 'key', code: event.code, pressed: event.type === 'keydown', modifiers };
}

export function socketUrl(path, lease, locationObject = window.location) {
  const protocol = locationObject.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${protocol}//${locationObject.host}${path}?lease=${encodeURIComponent(lease)}`;
}
