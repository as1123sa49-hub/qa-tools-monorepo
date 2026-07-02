import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { slotToSheet, sheetToSlot } from '../lib/slot-sheet.js';

describe('slot-sheet', () => {
  it('slotToSheet', () => {
    assert.equal(slotToSheet('Slot015'), 'S015');
    assert.equal(slotToSheet('slot002'), 'S002');
  });

  it('slotToSheet 無效格式', () => {
    assert.throws(() => slotToSheet('S015'), /無效的 Slot 格式/);
  });

  it('sheetToSlot', () => {
    assert.equal(sheetToSlot('S015'), 'Slot015');
    assert.equal(sheetToSlot('invalid'), null);
  });
});
