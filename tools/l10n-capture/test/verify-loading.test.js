import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { mergeConfig } from '../lib/config.js';
import { parseLoadingBatchText, assignLoadingMatches } from '../lib/verify.js';

describe('config mergeConfig', () => {
  it('深層合併 buyBonus.slotOverrides', () => {
    const defaults = {
      buyBonus: { slotOverrides: { Slot001: { landscapeCandidates: [{ x: 1, y: 2 }] } } },
    };
    const user = {
      buyBonus: { slotOverrides: { Slot002: { landscapeCandidates: [{ x: 3, y: 4 }] } } },
    };
    const out = mergeConfig(defaults, user);
    assert.deepEqual(out.buyBonus.slotOverrides.Slot001.landscapeCandidates[0], { x: 1, y: 2 });
    assert.deepEqual(out.buyBonus.slotOverrides.Slot002.landscapeCandidates[0], { x: 3, y: 4 });
  });

  it('合併 viewport 與 continue.slotOverrides', () => {
    const out = mergeConfig(
      { viewport: { width: 1920, height: 911 }, continue: { slotOverrides: {} } },
      { viewport: { height: 900 }, continue: { slotOverrides: { Slot024: { candidates: [{ x: 960, y: 820 }] } } } },
    );
    assert.equal(out.viewport.width, 1920);
    assert.equal(out.viewport.height, 900);
    assert.equal(out.continue.slotOverrides.Slot024.candidates[0].x, 960);
  });
});

describe('verify loading helpers', () => {
  it('parseLoadingBatchText 解析分頁', () => {
    const text = '---SLIDE 1---\nFirst\n---SLIDE 2---\nSecond';
    const pages = parseLoadingBatchText(text, 2);
    assert.deepEqual(pages, ['First', 'Second']);
  });

  it('parseLoadingBatchText 缺頁回傳 null', () => {
    assert.equal(parseLoadingBatchText('no markers', 2), null);
    assert.equal(parseLoadingBatchText('---SLIDE 1---\nOnly', 2), null);
  });

  it('assignLoadingMatches 跨張最佳配對', () => {
    const items = [
      { key: 'Loading_1', expectedText: 'Alpha promo' },
      { key: 'Loading_2', expectedText: 'Beta promo text' },
    ];
    const pages = [
      { file: 'Loading_1.png', lines: ['Beta promo text'] },
      { file: 'Loading_2.png', lines: ['Alpha promo'] },
    ];
    const map = assignLoadingMatches(items, pages);
    assert.equal(map.get('Loading_1').file, 'Loading_2.png');
    assert.equal(map.get('Loading_2').file, 'Loading_1.png');
    assert.ok(map.get('Loading_1').similarity >= 0.95);
    assert.ok(map.get('Loading_2').similarity >= 0.95);
  });
});
