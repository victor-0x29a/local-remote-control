import test from 'node:test';
import assert from 'node:assert/strict';


test('maps only terminal clipboard shortcuts', async () => {
  const { terminalShortcut } = await import('../src/local_remote_control/static/terminal-ui.js');

  assert.equal(terminalShortcut({ key: 'c', ctrlKey: true, shiftKey: true, altKey: false, metaKey: false }), 'copy');
  assert.equal(terminalShortcut({ key: 'V', ctrlKey: true, shiftKey: true, altKey: false, metaKey: false }), 'paste');
  assert.equal(terminalShortcut({ key: 'c', ctrlKey: true, shiftKey: false, altKey: false, metaKey: false }), null);
  assert.equal(terminalShortcut({ key: 'c', ctrlKey: true, shiftKey: true, altKey: true, metaKey: false }), null);
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
