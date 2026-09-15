export function terminalShortcut(event) {
  if (!event.ctrlKey || !event.shiftKey || event.altKey || event.metaKey) return null;
  const key = event.key.toLowerCase();
  if (key === 'c') return 'copy';
  if (key === 'v') return 'paste';
  return null;
}

export function terminalDimensions({ width, height, horizontalPadding, verticalPadding, cellWidth, cellHeight }) {
  const cols = Math.max(2, Math.floor((width - horizontalPadding) / cellWidth));
  const rows = Math.max(2, Math.floor((height - verticalPadding) / cellHeight));
  return { cols, rows };
}
