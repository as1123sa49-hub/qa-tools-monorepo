import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import {
  clickCandidateKey,
  isCachedClickNote,
  createCandidateCollector,
  addLearnedCandidate,
  buildLearnedClick,
} from '../lib/click-strategies.js';
import { orderContinueCandidates } from '../lib/continue-click.js';

describe('click-strategies', () => {
  it('clickCandidateKey 去重鍵', () => {
    assert.equal(clickCandidateKey({ pageX: 960.4, pageY: 810.6 }), '960,811');
    assert.equal(clickCandidateKey({ x: 100, y: 200 }), '100,200');
  });

  it('isCachedClickNote', () => {
    assert.equal(isCachedClickNote('快取座標'), true);
    assert.equal(isCachedClickNote('快取比例'), true);
    assert.equal(isCachedClickNote('左側掃描 fy=0.13'), false);
  });

  it('createCandidateCollector 略過重複座標', async () => {
    const { candidates, add } = createCandidateCollector();
    await add(960, 810, 'a');
    await add(960, 810, 'b');
    await add(961, 810, 'c');
    assert.equal(candidates.length, 2);
    assert.equal(candidates[0].note, 'a');
    assert.equal(candidates[1].note, 'c');
  });

  it('addLearnedCandidate 以快取座標優先加入（不需 page）', async () => {
    const { candidates, add } = createCandidateCollector();
    await addLearnedCandidate(add, null, { pageX: 500, pageY: 400, fx: 0.26, fy: 0.44 });
    assert.equal(candidates.length, 1);
    assert.equal(candidates[0].note, '快取座標');
    assert.equal(candidates[0].pageX, 500);
  });

  it('addLearnedCandidate 空值不加入', async () => {
    const { candidates, add } = createCandidateCollector();
    await addLearnedCandidate(add, null, null);
    await addLearnedCandidate(add, null, {});
    assert.equal(candidates.length, 0);
  });

  it('buildLearnedClick 已有 fraction 時四捨五入且不需 page', async () => {
    const out = await buildLearnedClick(null, { pageX: 960, pageY: 810, fx: 0.123456, fy: 0.987654 });
    assert.deepEqual(out, { pageX: 960, pageY: 810, fx: 0.1235, fy: 0.9877 });
  });
});

describe('orderContinueCandidates', () => {
  const center = { x: 960, y: 810 };
  const right = { x: 1375, y: 764 };
  const left = { x: 200, y: 800 };

  it('橫版：置中 → 偏右 → 其他', () => {
    const out = orderContinueCandidates([right, left, center], false);
    assert.deepEqual(out, [center, right, left]);
  });

  it('直版：略過偏右候選，置中優先', () => {
    const out = orderContinueCandidates([right, center, left], true);
    assert.deepEqual(out, [center, left]);
  });

  it('過濾非有限座標', () => {
    const out = orderContinueCandidates([{ x: NaN, y: 1 }, center], false);
    assert.deepEqual(out, [center]);
  });
});
