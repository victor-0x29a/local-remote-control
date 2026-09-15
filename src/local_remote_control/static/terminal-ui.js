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

export async function copyTerminalSelection(terminal, clipboard) {
  const text = terminal.getSelection();
  if (!text) return false;
  await clipboard.writeText(text);
  return true;
}

export async function pasteIntoTerminal(terminal, clipboard) {
  const text = await clipboard.readText();
  if (!text) return false;
  terminal.paste(text);
  return true;
}
