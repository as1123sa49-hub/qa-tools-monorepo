import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import {
  normalizeText,
  similarityRatio,
  findBestMatch,
  loadingCaptureFiles,
  buyCaptureFiles,
  filesForKey,
  isBuyKey,
} from '../lib/text-match.js';

describe('text-match', () => {
  it('normalizeText 全形與孟加拉數字', () => {
    assert.equal(normalizeText('ＡＢＣ'), 'ABC');
    assert.equal(normalizeText('০১২'), '012');
    assert.equal(normalizeText('  hello   world  '), 'hello world');
  });

  it('similarityRatio 相同與不同', () => {
    assert.equal(similarityRatio('abc', 'abc'), 1);
    assert.equal(similarityRatio('', ''), 1);
    assert.equal(similarityRatio('abc', 'xyz'), 0);
    assert.ok(similarityRatio('hello world', 'hello worl') > 0.9);
  });

  it('findBestMatch 單行命中', () => {
    const hit = findBestMatch('Play Now', ['Welcome', 'Play Now', 'Footer']);
    assert.ok(hit.similarity >= 0.95);
    assert.equal(hit.lineStart, 1);
    assert.equal(hit.lineEnd, 1);
  });

  it('loadingCaptureFiles 依數字排序', () => {
    const files = loadingCaptureFiles(['Loading_10.png', 'Loading_2.png', 'buy_popup.png']);
    assert.deepEqual(files, ['Loading_2.png', 'Loading_10.png']);
  });

  it('buyCaptureFiles 與 isBuyKey', () => {
    assert.equal(isBuyKey('Buy_Bet'), true);
    assert.equal(isBuyKey('Loading_1'), false);
    assert.deepEqual(buyCaptureFiles(['info_scroll_01.png', 'buy_popup.png']), ['buy_popup.png']);
  });

  it('filesForKey 路由', () => {
    const all = ['Loading_1.png', 'Loading_2.png', 'buy_popup.png', 'info_scroll_01.png'];
    assert.deepEqual(filesForKey('Loading_2', all), ['Loading_2.png']);
    assert.deepEqual(filesForKey('Buy_Bet', all), ['buy_popup.png']);
    assert.deepEqual(filesForKey('Info_1', all), ['info_scroll_01.png']);
  });
});
