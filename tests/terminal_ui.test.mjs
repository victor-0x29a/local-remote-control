import test from 'node:test';
import assert from 'node:assert/strict';


test('maps only terminal clipboard shortcuts', async () => {
  const { terminalShortcut } = await import('../src/local_remote_control/static/terminal-ui.js');

  assert.equal(terminalShortcut({ key: 'c', ctrlKey: true, shiftKey: true, altKey: false, metaKey: false }), 'copy');
  assert.equal(terminalShortcut({ key: 'V', ctrlKey: true, shiftKey: true, altKey: false, metaKey: false }), 'paste');
  assert.equal(terminalShortcut({ key: 'c', ctrlKey: true, shiftKey: false, altKey: false, metaKey: false }), null);
  assert.equal(terminalShortcut({ key: 'c', ctrlKey: true, shiftKey: true, altKey: true, metaKey: false }), null);
});


test('keeps editable and terminal keystrokes on the client device', async () => {
  const { shouldForwardRemoteKey } = await import('../src/local_remote_control/static/terminal-ui.js');

  assert.equal(shouldForwardRemoteKey({ keyboardCaptured: true, insideTerminal: false, editable: false }), true);
  assert.equal(shouldForwardRemoteKey({ keyboardCaptured: true, insideTerminal: true, editable: false }), false);
  assert.equal(shouldForwardRemoteKey({ keyboardCaptured: true, insideTerminal: false, editable: true }), false);
  assert.equal(shouldForwardRemoteKey({ keyboardCaptured: false, insideTerminal: false, editable: false }), false);
});


test('calculates terminal rows and columns from usable panel space', async () => {
  const { terminalDimensions } = await import('../src/local_remote_control/static/terminal-ui.js');

  assert.deepEqual(
    terminalDimensions({ width: 800, height: 400, horizontalPadding: 16, verticalPadding: 16, cellWidth: 10, cellHeight: 20 }),
    { cols: 78, rows: 19 },
  );
  assert.deepEqual(
    terminalDimensions({ width: 10, height: 10, horizontalPadding: 16, verticalPadding: 16, cellWidth: 10, cellHeight: 20 }),
    { cols: 2, rows: 2 },
  );
});


test('copies only a non-empty terminal selection', async () => {
  const { copyTerminalSelection } = await import('../src/local_remote_control/static/terminal-ui.js');
  const clipboard = new MemoryClipboard();

  assert.equal(await copyTerminalSelection({ getSelection: () => '' }, clipboard), false);
  assert.equal(await copyTerminalSelection({ getSelection: () => 'linha selecionada' }, clipboard), true);
  assert.equal(clipboard.text, 'linha selecionada');
});


test('pastes clipboard text through the terminal paste API', async () => {
  const { pasteIntoTerminal } = await import('../src/local_remote_control/static/terminal-ui.js');
  const clipboard = new MemoryClipboard('comando --seguro');
  const pasted = [];

  assert.equal(await pasteIntoTerminal({ paste: (text) => pasted.push(text) }, clipboard), true);
  assert.deepEqual(pasted, ['comando --seguro']);

  clipboard.text = '';
  assert.equal(await pasteIntoTerminal({ paste: (text) => pasted.push(text) }, clipboard), false);
  assert.deepEqual(pasted, ['comando --seguro']);
});


class MemoryClipboard {
  constructor(text = '') {
    this.text = text;
  }

  async readText() {
    return this.text;
  }

  async writeText(text) {
    this.text = text;
  }
}
