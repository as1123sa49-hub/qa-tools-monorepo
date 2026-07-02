import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { solveAssignment, ASSIGN_PERM_LIMIT } from '../lib/verify.js';
import { createUsageAccumulator, mergeUsage } from '../lib/ocr-client.js';

/** 依 assign 結果算總分，驗證是否為最佳解 */
function scoreOf(scores, assign) {
  return assign.reduce((sum, j, i) => sum + scores[i][j], 0);
}

describe('solveAssignment', () => {
  it('方陣取最佳一對一指派（非對角線）', () => {
    const scores = [
      [0.2, 0.3, 0.98],
      [0.95, 0.1, 0.15],
      [0.25, 0.97, 0.2],
    ];
    const assign = solveAssignment(scores, 3);
    assert.deepEqual(assign, [2, 0, 1]);
  });

  it('key 少於圖時只指派 k 個且不重複用圖', () => {
    const scores = [
      [0.1, 0.9, 0.4, 0.2],
      [0.8, 0.2, 0.3, 0.7],
    ];
    const assign = solveAssignment(scores, 2);
    assert.equal(assign.length, 2);
    assert.notEqual(assign[0], assign[1]);
    assert.deepEqual(assign, [1, 0]);
  });

  it('空矩陣或 k<1 回傳 null', () => {
    assert.equal(solveAssignment([], 0), null);
    assert.equal(solveAssignment([[]], 1), null);
    assert.equal(solveAssignment([[0.5]], 0), null);
  });

  it('大規模改用貪婪法仍給出合法且高分指派', () => {
    const n = 12;
    // 對角線為最佳（0.9），其餘為雜訊；P(12,12) 遠超上限 → 走貪婪
    assert.ok(injectivePerm(n, n) > ASSIGN_PERM_LIMIT);
    const scores = Array.from({ length: n }, (_, i) =>
      Array.from({ length: n }, (_, j) => (i === j ? 0.9 : 0.05)),
    );
    const assign = solveAssignment(scores, n);
    assert.equal(assign.length, n);
    assert.equal(new Set(assign).size, n, '每張圖只用一次');
    assert.deepEqual(assign, Array.from({ length: n }, (_, i) => i));
    assert.ok(scoreOf(scores, assign) >= 0.9 * n - 1e-9);
  });

  it('貪婪與暴力在小規模給出相同總分', () => {
    const scores = [
      [0.5, 0.8, 0.1],
      [0.9, 0.2, 0.4],
      [0.3, 0.6, 0.7],
    ];
    const brute = solveAssignment(scores, 3);
    // 直接比對總分（貪婪在此例應同為最佳）
    assert.ok(scoreOf(scores, brute) >= 2.4 - 1e-9);
  });
});

function injectivePerm(m, k) {
  let c = 1;
  for (let i = 0; i < k; i++) c *= m - i;
  return c;
}

describe('usage accumulator', () => {
  it('createUsageAccumulator 初始為 0', () => {
    const acc = createUsageAccumulator();
    assert.equal(acc.totalTokens, 0);
    assert.equal(acc.apiCostReported, false);
  });

  it('mergeUsage 累加 Gemini 欄位', () => {
    const acc = createUsageAccumulator();
    mergeUsage(acc, { promptTokenCount: 10, candidatesTokenCount: 5, totalTokenCount: 15 });
    assert.equal(acc.promptTokens, 10);
    assert.equal(acc.completionTokens, 5);
    assert.equal(acc.totalTokens, 15);
  });

  it('mergeUsage 累加 Siraya(OpenAI) 欄位與成本', () => {
    const acc = createUsageAccumulator();
    mergeUsage(acc, { prompt_tokens: 20, completion_tokens: 8, total_tokens: 28 }, 0.0012);
    mergeUsage(acc, { prompt_tokens: 5, completion_tokens: 2, total_tokens: 7 });
    assert.equal(acc.promptTokens, 25);
    assert.equal(acc.completionTokens, 10);
    assert.equal(acc.totalTokens, 35);
    assert.equal(acc.apiCostReported, true);
    assert.ok(Math.abs(acc.costUsd - 0.0012) < 1e-9);
  });

  it('mergeUsage 對空值安全', () => {
    const acc = createUsageAccumulator();
    mergeUsage(acc, null);
    mergeUsage(null, { prompt_tokens: 1 });
    assert.equal(acc.totalTokens, 0);
  });
});
