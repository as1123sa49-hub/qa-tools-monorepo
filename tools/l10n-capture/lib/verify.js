import fs from 'node:fs/promises';
import path from 'node:path';
import {
  buyCaptureFiles,
  findBestMatch,
  filesForKey,
  infoCaptureFiles,
  isBuyKey,
  loadingCaptureFiles,
} from './text-match.js';
import { PROVIDER_GEMINI, PROVIDER_SIRAYA } from './llm-providers.js';
import { loadConfig } from './capture-flow.js';
import {
  OCR_PROMPT,
  createUsageAccumulator,
  mergeUsage,
  ocrImage,
  ocrMultiImages,
} from './ocr-client.js';

export { createUsageAccumulator, mergeUsage, ocrImage } from './ocr-client.js';
import { loadCaptureMetaFromDir } from './capture-meta.js';
import {
  formatPromoRegion,
  resolveLoadingPromoRegion,
} from './loading-promo-region.js';
import {
  CACHE_VERSION,
  createOcrCache,
  isCacheMetaMatch,
  isEntryReusable,
  isInfoScrollFile,
  isLoadingFile,
  loadOcrCache,
  OCR_SCHEMA_SHARED,
  OCR_SCHEMA_SINGLE,
  prepareOcrBuffer,
  prepareLoadingOcrBuffer,
  resolveOcrText,
  saveOcrCache,
  textToLines,
  cropRegionKey,
} from './ocr-utils.js';
import { imageDiffRatio } from './image-diff.js';

export const PASS_THRESHOLD = 0.95;
export const REVIEW_THRESHOLD = 0.85;

const LOADING_OCR_PROMPT =
  'This image is the promotional carousel area of a game loading screen. '
  + 'Extract ALL visible promotional text only. Return ONLY the extracted text in its original language and script. '
  + 'Preserve numbers and symbols. Do not translate. Do not add explanations or markdown.';

const LOADING_BATCH_PROMPT =
  'You receive loading screen images in order (image 1, then 2, then 3, etc.). '
  + 'Extract ALL visible text from EACH image separately. '
  + 'Return ONLY in this exact format (no other text):\n'
  + '---SLIDE 1---\n<text from image 1>\n'
  + '---SLIDE 2---\n<text from image 2>\n'
  + '(continue for each image). Preserve original language, numbers and symbols.';

/** 解析合併 Loading OCR 的分頁標記；失敗回傳 null */
export function parseLoadingBatchText(text, slideCount) {
  if (!text || slideCount < 1) return null;
  const sections = new Map();
  const re = /---SLIDE\s*(\d+)\s*---/gi;
  const parts = text.split(re);
  if (parts.length < 3) return null;
  for (let i = 1; i < parts.length; i += 2) {
    const num = parseInt(parts[i], 10);
    const body = (parts[i + 1] || '').trim();
    if (num >= 1 && num <= slideCount) sections.set(num, body);
  }
  if (sections.size < slideCount) return null;
  return Array.from({ length: slideCount }, (_, i) => sections.get(i + 1) || '');
}

function loadingDisplayFile(key, loadingFiles) {
  const n = key.match(/^Loading_(\d+)$/i)?.[1];
  if (!n) return '';
  const target = `Loading_${n}.png`;
  return loadingFiles.find(f => f.toLowerCase() === target.toLowerCase()) || '';
}

const DEFAULT_VERIFY_OPTS = {
  ocrMaxWidth: 1280,
  ocrJpegQuality: 85,
  maxOutputTokens: 4096,
  ocrCache: true,
  loadingBatchOcr: false,
  loadingCrossMatch: true,
  loadingOcrCrop: true,
  scrollDedupThreshold: 0.05,
};

/** 暴力最佳指派的排列數上限（= P(m,k)）；超過改用貪婪法，避免階乘爆炸 */
export const ASSIGN_PERM_LIMIT = 50000;

/** 由 k 個 key 映射到 m 張圖的injective排列數 P(m,k) = m·(m-1)···(m-k+1) */
function injectivePermCount(m, k) {
  let c = 1;
  for (let i = 0; i < k; i++) c *= m - i;
  return c;
}

/** 暴力法：列舉所有組合×排列取總分最高（k! 等級，僅小規模使用） */
function bruteAssignment(scores, k, m) {
  function permutations(arr, len) {
    if (len === 0) return [[]];
    const out = [];
    for (let i = 0; i < arr.length; i++) {
      const rest = [...arr.slice(0, i), ...arr.slice(i + 1)];
      for (const tail of permutations(rest, len - 1)) {
        out.push([arr[i], ...tail]);
      }
    }
    return out;
  }

  function* combinations(start, chosen) {
    if (chosen.length === k) {
      yield chosen.slice();
      return;
    }
    for (let i = start; i <= m - (k - chosen.length); i++) {
      chosen.push(i);
      yield* combinations(i + 1, chosen);
      chosen.pop();
    }
  }

  let bestAssign = null;
  let bestScore = -1;
  const combos = m === k
    ? [Array.from({ length: m }, (_, i) => i)]
    : [...combinations(0, [])];

  for (const combo of combos) {
    for (const perm of permutations(combo, k)) {
      let total = 0;
      for (let i = 0; i < k; i++) total += scores[i][perm[i]];
      if (total > bestScore) {
        bestScore = total;
        bestAssign = perm;
      }
    }
  }
  return bestAssign;
}

/** 貪婪法：所有 (key, 圖) 依相似度由高到低指派，各 key/圖 只用一次（O(k·m·log) ） */
function greedyAssignment(scores, k, m) {
  const triples = [];
  for (let i = 0; i < k; i++) {
    for (let j = 0; j < m; j++) triples.push({ i, j, s: scores[i][j] });
  }
  triples.sort((a, b) => b.s - a.s);
  const assign = new Array(k).fill(-1);
  const usedPage = new Set();
  let assigned = 0;
  for (const t of triples) {
    if (assigned === k) break;
    if (assign[t.i] !== -1 || usedPage.has(t.j)) continue;
    assign[t.i] = t.j;
    usedPage.add(t.j);
    assigned++;
  }
  return assign.some(v => v === -1) ? null : assign;
}

/**
 * 從 n×m 的相似度矩陣找出 k=min(n,m) 個 key 對圖的最佳一對一指派。
 * 小規模用暴力最佳解；規模過大（P(m,k) > ASSIGN_PERM_LIMIT）改用貪婪近似，避免階乘爆炸。
 * @param {number[][]} scores 每列為一個 key 對各圖的相似度
 * @returns {number[]|null} assign[i] = 指派給第 i 個 key 的圖索引
 */
export function solveAssignment(scores, k = Math.min(scores.length, scores[0]?.length ?? 0)) {
  const n = scores.length;
  const m = scores[0]?.length ?? 0;
  if (!n || !m || k < 1) return null;
  return injectivePermCount(m, k) > ASSIGN_PERM_LIMIT
    ? greedyAssignment(scores, k, m)
    : bruteAssignment(scores, k, m);
}

/** Loading key 與各張截圖的最佳 1:1 配對（解決輪播順序 ≠ 檔名順序） */
export function assignLoadingMatches(loadingItems, loadingPages) {
  const n = loadingItems.length;
  const m = loadingPages.length;
  const result = new Map();
  if (!n || !m) return result;

  const matrix = loadingItems.map(item =>
    loadingPages.map(page => ({
      ...findBestMatch(item.expectedText, page.lines),
      file: page.file,
      rawText: page.lines.join(' ').trim(),
    })),
  );

  const k = Math.min(n, m);
  const scores = matrix.map(row => row.map(cell => cell.similarity));
  const bestAssign = solveAssignment(scores, k);
  if (!bestAssign) return result;

  for (let i = 0; i < k; i++) {
    const pageIdx = bestAssign[i];
    const hit = matrix[i][pageIdx];
    const snippet = hit.snippet || hit.rawText || '';
    result.set(loadingItems[i].key, {
      similarity: hit.similarity,
      snippet,
      file: hit.file,
      lineStart: hit.lineStart,
      lineEnd: hit.lineEnd,
      totalLines: hit.totalLines,
      highlightLines: hit.highlightLines.length ? hit.highlightLines : (snippet ? [snippet] : []),
      bandReliable: hit.bandReliable,
      matchType: hit.matchType,
      matchNote: hit.matchNote,
    });
  }
  return result;
}

function statusOf(similarity) {
  if (similarity >= PASS_THRESHOLD) return 'PASS';
  if (similarity >= REVIEW_THRESHOLD) return 'REVIEW';
  return 'FAIL';
}

async function countCacheCoverage(imagesDir, cache, ocrFiles, loadingPromoRegion, loadingCropLayout, loadingCropRegionKey, { forceOcr = false, forceOcrFiles = null } = {}) {
  const forceSet = forceOcrFiles instanceof Set ? forceOcrFiles : forceOcrFiles ? new Set(forceOcrFiles) : null;
  if (!cache?.entries || forceOcr) return { ready: 0, total: ocrFiles.length };
  let ready = 0;
  for (const file of ocrFiles) {
    if (forceSet?.has(file)) continue;
    const filePath = path.join(imagesDir, file);
    try {
      const stat = await fs.stat(filePath);
      const hit = cache.entries[file];
      const useLoadingCrop = isLoadingFile(file) && Boolean(loadingPromoRegion?.width);
      if (hit && hit.mtimeMs === stat.mtimeMs && isEntryReusable(hit, file, {
        expectLoadingCrop: useLoadingCrop,
        expectLoadingCropLayout: useLoadingCrop ? loadingCropLayout : undefined,
        expectLoadingCropRegion: useLoadingCrop ? loadingCropRegionKey : undefined,
      })) {
        ready++;
      }
    } catch { /* 檔案不存在 */ }
  }
  return { ready, total: ocrFiles.length };
}

async function resolveVerifyOpts(verifyOpts = {}) {
  const cfg = await loadConfig();
  return { ...DEFAULT_VERIFY_OPTS, ...cfg.verify, ...verifyOpts };
}

async function runLoadingBatchOcr({
  loadingFiles,
  imagesDir,
  cache,
  cacheEnabled,
  forceOcr,
  prepareOpts,
  loadingPromoRegion,
  loadingCropLayout,
  loadingCropRegionKey,
  provider,
  apiKey,
  modelId,
  maxOutputTokens,
  onLog,
  usageAcc,
}) {
  const filePaths = loadingFiles.map(f => path.join(imagesDir, f));
  const stats = await Promise.all(filePaths.map(p => fs.stat(p)));
  const useCrop = Boolean(loadingPromoRegion?.width);

  if (!forceOcr && cacheEnabled && cache) {
    const allHit = loadingFiles.every((f, i) => {
      const hit = cache.entries?.[f];
      return hit && hit.mtimeMs === stats[i].mtimeMs
        && isEntryReusable(hit, f, {
          expectLoadingCrop: useCrop,
          expectLoadingCropLayout: useCrop ? loadingCropLayout : undefined,
          expectLoadingCropRegion: useCrop ? loadingCropRegionKey : undefined,
        });
    });
    if (allHit) {
      onLog(`  OCR Loading×${loadingFiles.length}（快取）`);
      return {
        textByFile: new Map(loadingFiles.map(f => [f, cache.entries[f].text])),
        apiCalls: 0,
        cacheHits: loadingFiles.length,
      };
    }
  }

  const buffers = await Promise.all(filePaths.map(p => fs.readFile(p)));
  const prepareOne = useCrop
    ? b => prepareLoadingOcrBuffer(b, loadingPromoRegion, prepareOpts)
    : b => prepareOcrBuffer(b, prepareOpts);
  const prepared = await Promise.all(buffers.map(prepareOne));
  const ocrPrompt = useCrop ? LOADING_OCR_PROMPT : LOADING_BATCH_PROMPT;
  const rawText = await ocrMultiImages(
    provider, apiKey, modelId, prepared, ocrPrompt, maxOutputTokens, usageAcc
  );
  const slideTexts = parseLoadingBatchText(rawText, loadingFiles.length);
  const splitOk = Boolean(slideTexts);
  if (splitOk) {
    onLog(`  OCR Loading 合併 ${loadingFiles.length} 張（API，已分頁）`);
  } else {
    onLog(`  OCR Loading 合併 ${loadingFiles.length} 張（API，分頁解析失敗，各張共用全文）`);
  }

  const schema = splitOk ? OCR_SCHEMA_SINGLE : OCR_SCHEMA_SHARED;
  const textByFile = new Map();
  for (let i = 0; i < loadingFiles.length; i++) {
    const f = loadingFiles[i];
    const text = splitOk ? slideTexts[i] : rawText;
    textByFile.set(f, text);
    if (cacheEnabled && cache) {
      cache.entries[f] = {
        mtimeMs: stats[i].mtimeMs,
        text,
        schema,
        ...(useCrop ? {
          loadingCrop: true,
          loadingCropLayout: loadingCropLayout || 'unknown',
          loadingCropRegion: loadingCropRegionKey || '',
        } : {}),
      };
    }
  }
  return { textByFile, apiCalls: 1, cacheHits: 0 };
}

/**
 * 驗證單一 Slot：OCR 截圖（快取 + 縮圖），逐 key 在 OCR 文字中尋找最相似片段。
 * @param {object} opts
 * @param {string} opts.imagesDir 截圖資料夾
 * @param {Array<{key:string, expectedText:string}>} opts.items 該 Slot 的 bn 預期字串
 * @param {string} opts.apiKey
 * @param {string} opts.modelId
 * @param {boolean} [opts.forceOcr] 略過 OCR 快取
 * @param {function} [opts.onLog]
 */
export async function verifySlot({
  imagesDir,
  items,
  provider = PROVIDER_GEMINI,
  apiKey,
  modelId,
  forceOcr = false,
  forceOcrFiles = null,
  verifyOpts,
  signal,
  onLog = () => {},
}) {
  const vOpts = await resolveVerifyOpts(verifyOpts);
  const cfg = await loadConfig();
  const {
    ocrMaxWidth,
    ocrJpegQuality,
    maxOutputTokens,
    ocrCache: cacheEnabled,
    loadingBatchOcr,
    loadingCrossMatch,
    loadingOcrCrop,
    scrollDedupThreshold,
  } = vOpts;
  const prepareOpts = { maxWidth: ocrMaxWidth, jpegQuality: ocrJpegQuality };
  const textRegion = cfg.infoScroll?.textRegion;
  const dupThreshold = scrollDedupThreshold ?? cfg.infoScroll?.saveMovedThreshold ?? 0.05;

  const captureMeta = await loadCaptureMetaFromDir(imagesDir);
  const promoResolved = loadingOcrCrop !== false
    ? resolveLoadingPromoRegion(captureMeta, cfg)
    : { region: null, portraitLayout: null, layoutKey: 'none' };
  const loadingPromoRegion = promoResolved.region;
  const loadingCropLayout = promoResolved.layoutKey;
  const loadingCropRegionKey = cropRegionKey(loadingPromoRegion);
  if (loadingPromoRegion?.width) {
    const layoutLabel = promoResolved.portraitLayout === true
      ? '直版'
      : promoResolved.portraitLayout === false
        ? '橫版'
        : '橫版（推定）';
    onLog(`  Loading OCR 促銷文字帶裁切（${layoutLabel}）${formatPromoRegion(loadingPromoRegion)}`);
  }

  const files = await listPngs(imagesDir);
  if (files === null) throw new Error(`找不到截圖資料夾：${imagesDir}（請先執行擷取）`);
  if (!files.length) throw new Error(`資料夾無 PNG 截圖：${imagesDir}`);

  const ocrFiles = files;
  const forceSet = forceOcrFiles instanceof Set
    ? forceOcrFiles
    : forceOcrFiles
      ? new Set(forceOcrFiles)
      : null;

  let cache = null;
  if (cacheEnabled) {
    const loaded = await loadOcrCache(imagesDir);
    if (loaded && isCacheMetaMatch(loaded, { provider, modelId, maxWidth: ocrMaxWidth })) {
      cache = loaded;
      cache.version = CACHE_VERSION;
      if (!cache.entries) cache.entries = {};
    } else {
      cache = createOcrCache({ provider, modelId, maxWidth: ocrMaxWidth });
      if (loaded) {
        onLog(`  OCR 快取 metaKey 不符（${loaded.metaKey}），將重建快取`);
      }
    }
  }

  const cacheBefore = await countCacheCoverage(
    imagesDir, cache, ocrFiles, loadingPromoRegion, loadingCropLayout, loadingCropRegionKey, {
    forceOcr,
    forceOcrFiles: forceSet,
  });
  onLog(`  OCR 快取覆蓋 ${cacheBefore.ready}/${cacheBefore.total} 張（驗證前）`);

  const tokenUsage = createUsageAccumulator();

  const ocrFn = async rawBuffer => {
    const { buffer, mimeType } = await prepareOcrBuffer(rawBuffer, prepareOpts);
    return ocrImage({ provider, apiKey, modelId, buffer, mimeType, maxOutputTokens, usageAcc: tokenUsage });
  };

  const loadingOcrFn = async rawBuffer => {
    const prep = loadingPromoRegion?.width
      ? await prepareLoadingOcrBuffer(rawBuffer, loadingPromoRegion, prepareOpts)
      : await prepareOcrBuffer(rawBuffer, prepareOpts);
    const prompt = loadingPromoRegion?.width ? LOADING_OCR_PROMPT : OCR_PROMPT;
    return ocrImage({
      provider,
      apiKey,
      modelId,
      buffer: prep.buffer,
      mimeType: prep.mimeType,
      maxOutputTokens,
      usageAcc: tokenUsage,
      prompt,
    });
  };

  const ocrPages = [];
  let cacheHits = 0;
  let apiCalls = 0;
  let scrollDeduped = 0;
  let ocrFailed = 0;

  const loadingInOcr = loadingCaptureFiles(ocrFiles);
  const loadingBatchDone = new Set();

  if (loadingBatchOcr && loadingInOcr.length >= 2 && !signal?.aborted) {
    const batchForceOcr = forceOcr || Boolean(forceSet && loadingInOcr.some(f => forceSet.has(f)));
    try {
      const batch = await runLoadingBatchOcr({
        loadingFiles: loadingInOcr,
        imagesDir,
        cache,
        cacheEnabled,
        forceOcr: batchForceOcr,
        prepareOpts,
        loadingPromoRegion,
        loadingCropLayout,
        loadingCropRegionKey,
        provider,
        apiKey,
        modelId,
        maxOutputTokens,
        onLog,
        usageAcc: tokenUsage,
      });
      cacheHits += batch.cacheHits;
      apiCalls += batch.apiCalls;
      for (const f of loadingInOcr) {
        const text = batch.textByFile.get(f) || '';
        ocrPages.push({ file: f, lines: textToLines(text) });
        loadingBatchDone.add(f);
      }
    } catch (err) {
      // 合併 OCR 失敗 → 不中斷，交回主迴圈逐張處理（各自 try/catch）
      onLog(`  ⚠ Loading 合併 OCR 失敗，改逐張處理：${String(err.message || err)}`);
    }
  }

  let prevScrollBuf = null;
  let prevScrollLines = null;
  let prevScrollFile = '';

  for (const file of ocrFiles) {
    if (signal?.aborted) {
      onLog('  驗證已中斷（連線關閉）');
      break;
    }
    if (loadingBatchDone.has(file)) continue;

    const filePath = path.join(imagesDir, file);
    let textOverride = null;
    let rawBuf = null;

    if (isInfoScrollFile(file)) {
      rawBuf = await fs.readFile(filePath);
      if (prevScrollBuf && prevScrollLines && textRegion) {
        const ratio = await imageDiffRatio(prevScrollBuf, rawBuf, textRegion);
        if (ratio < dupThreshold) {
          textOverride = prevScrollLines.join('\n');
          scrollDeduped++;
          onLog(`  OCR ${file}（略過重複，同 ${prevScrollFile}）`);
        } else {
          prevScrollBuf = rawBuf;
        }
      } else {
        prevScrollBuf = rawBuf;
      }
    }

    let text = '';
    let fromCache = false;
    let failed = false;
    const fileIsLoading = isLoadingFile(file);
    const useLoadingCrop = fileIsLoading && Boolean(loadingPromoRegion?.width);
    const forceThisFile = forceOcr || Boolean(forceSet?.has(file));
    try {
      const r = await resolveOcrText({
        imagesDir,
        file,
        cache,
        cacheEnabled,
        forceOcr: forceThisFile,
        filePath,
        expectLoadingCrop: useLoadingCrop,
        expectLoadingCropLayout: useLoadingCrop ? loadingCropLayout : undefined,
        expectLoadingCropRegion: useLoadingCrop ? loadingCropRegionKey : undefined,
        ocrFn: async () => {
          try {
            const buf = rawBuf ?? await fs.readFile(filePath);
            if (useLoadingCrop) return loadingOcrFn(buf);
            return ocrFn(buf);
          } catch (err) {
            throw new Error(`${file}：${err.message}`);
          }
        },
        textOverride,
      });
      text = r.text;
      fromCache = r.fromCache;
    } catch (err) {
      // 單張 OCR 失敗 → 記為空白，不中斷整批（該張相關 key 可能 FAIL）
      failed = true;
      ocrFailed++;
      onLog(`  ⚠ OCR ${file} 失敗，跳過此張：${String(err.message || err)}`);
    }

    if (failed) {
      // 不寫入快取，讓下次可重試
    } else if (textOverride) {
      // 已寫入快取
    } else if (fromCache) {
      cacheHits++;
    } else {
      apiCalls++;
      if (useLoadingCrop) {
        onLog(`  OCR ${file}（輪播區裁切）`);
      }
    }

    const lines = textToLines(text);
    ocrPages.push({ file, lines });

    if (isInfoScrollFile(file) && !textOverride && !failed) {
      prevScrollLines = lines;
      prevScrollFile = file;
    }

    if (!textOverride && !failed) {
      const tag = fromCache ? '快取' : 'API';
      onLog(`  OCR ${file}（${tag}）→ ${text.replace(/\s+/g, '').length} 字`);
    }
  }

  if (cacheEnabled && cache && !signal?.aborted) {
    await saveOcrCache(imagesDir, cache);
  }
  if (!signal?.aborted && (apiCalls > 0 || cacheHits > 0 || scrollDeduped > 0 || ocrFailed > 0)) {
    const parts = [`API ${apiCalls} 次`, `快取 ${cacheHits}`];
    if (scrollDeduped > 0) parts.push(`scroll 去重 ${scrollDeduped}`);
    if (ocrFailed > 0) parts.push(`OCR 失敗 ${ocrFailed}`);
    if (loadingBatchDone.size >= 2) parts.push('Loading 已合併');
    if (tokenUsage.totalTokens > 0) {
      parts.push(`token ${tokenUsage.promptTokens} in / ${tokenUsage.completionTokens} out`);
      if (tokenUsage.apiCostReported) parts.push(`$${tokenUsage.costUsd.toFixed(4)}`);
    }
    onLog(`  OCR 統計：${parts.join('、')}`);
  }

  if (signal?.aborted) {
    return {
      imagesDir,
      images: files.length,
      ocrCount: ocrPages.length,
      ocrApiCalls: apiCalls,
      cacheHits,
      cacheCoverage: { ready: cacheHits, total: ocrFiles.length },
      cacheTotal: ocrFiles.length,
      scrollDeduped,
      ocrFailed,
      tokenUsage,
      results: [],
      summary: { PASS: 0, REVIEW: 0, FAIL: 0 },
      aborted: true,
    };
  }

  const { results, summary } = matchItemsToOcr({
    items,
    files,
    ocrPages,
    loadingCrossMatch,
    onLog,
  });

  const cacheReadyAfter = ocrFiles.length - apiCalls - ocrFailed;

  return {
    imagesDir,
    images: files.length,
    ocrCount: ocrPages.length,
    ocrApiCalls: apiCalls,
    cacheHits,
    cacheCoverage: { ready: cacheReadyAfter, total: ocrFiles.length },
    cacheTotal: ocrFiles.length,
    scrollDeduped,
    ocrFailed,
    tokenUsage,
    results,
    summary,
  };
}

/** 將 OCR 頁面與工作表 key 比對（Loading 跨張配對 + 覆蓋式搜尋） */
export function matchItemsToOcr({
  items,
  files,
  ocrPages,
  loadingCrossMatch = true,
  onLog = () => {},
}) {
  const loadingAssignment = new Map();
  const loadingItemsForMatch = items.filter(i => /^Loading_\d+$/i.test(i.key));
  const loadingPagesForMatch = ocrPages.filter(p => /^loading_\d+\.png$/i.test(p.file));
  if (loadingCrossMatch !== false && loadingItemsForMatch.length && loadingPagesForMatch.length) {
    const assigned = assignLoadingMatches(loadingItemsForMatch, loadingPagesForMatch);
    for (const [key, match] of assigned) loadingAssignment.set(key, match);
    if (loadingItemsForMatch.length >= 2) {
      const pairs = [...assigned.entries()]
        .map(([key, m]) => `${key}→${m.file} ${(m.similarity * 100).toFixed(0)}%`)
        .join('、');
      onLog(`  Loading 跨張配對（${loadingItemsForMatch.length} key × ${loadingPagesForMatch.length} 張）：${pairs}`);
    }
  }

  const results = [];
  for (const item of items) {
    const isLoadingKey = /^Loading_\d+$/i.test(item.key);
    const itemIsBuyKey = isBuyKey(item.key);
    const loadingFiles = loadingCaptureFiles(files);
    const buyFiles = buyCaptureFiles(files);

    const crossMatched = isLoadingKey && loadingAssignment.has(item.key);
    const keyFiles = crossMatched
      ? [loadingAssignment.get(item.key).file]
      : filesForKey(item.key, files);
    const searchFiles = new Set(keyFiles);
    const pages = keyFiles.length
      ? ocrPages.filter(p => searchFiles.has(p.file))
      : [];

    if (pages.length === 0 && isLoadingKey) {
      const loadingFiles = loadingCaptureFiles(files);
      results.push({
        key: item.key,
        expected: item.expectedText,
        similarity: 0,
        status: 'FAIL',
        sourceFile: '',
        displayFile: loadingDisplayFile(item.key, loadingFiles),
        snippet: '',
        lineStart: -1,
        lineEnd: -1,
        totalLines: 0,
        highlightLines: [],
        issueNote: '找不到 Loading_*.png 截圖，請先擷取',
        isLoadingKey: true,
      });
      continue;
    }

    if (pages.length === 0 && isBuyKey(item.key)) {
      const buyFiles = buyCaptureFiles(files);
      results.push({
        key: item.key,
        expected: item.expectedText,
        similarity: 0,
        status: 'FAIL',
        sourceFile: buyFiles[0] || '',
        snippet: '',
        lineStart: -1,
        lineEnd: -1,
        totalLines: 0,
        highlightLines: [],
        issueNote: buyFiles.length
          ? 'buy_*.png 尚未 OCR 或無可用文字'
          : '找不到 buy_*.png 截圖，請先擷取 Buy 彈窗或手動貼圖',
        isBuyKey: true,
      });
      continue;
    }

    if (pages.length === 0) {
      const infoFiles = infoCaptureFiles(files);
      results.push({
        key: item.key,
        expected: item.expectedText,
        similarity: 0,
        status: 'FAIL',
        sourceFile: infoFiles[0] || '',
        snippet: '',
        lineStart: -1,
        lineEnd: -1,
        totalLines: 0,
        highlightLines: [],
        issueNote: infoFiles.length
          ? 'info_scroll_*.png 尚未 OCR 或無可用文字'
          : '找不到 info_scroll_*.png 截圖，請先擷取 Info',
      });
      continue;
    }

    let best = crossMatched
      ? { ...loadingAssignment.get(item.key), matchType: loadingAssignment.get(item.key).matchType || 'cross-match' }
      : {
        similarity: 0,
        snippet: '',
        file: '',
        lineStart: -1,
        lineEnd: -1,
        totalLines: 0,
        highlightLines: [],
        bandReliable: false,
        matchType: 'none',
        matchNote: '',
      };

    if (!crossMatched) {
      for (const page of pages) {
        const m = findBestMatch(item.expectedText, page.lines);
        if (m.similarity > best.similarity) {
          best = {
            similarity: m.similarity,
            snippet: m.snippet || page.lines.join(' ').trim(),
            file: page.file,
            lineStart: m.lineStart,
            lineEnd: m.lineEnd,
            totalLines: m.totalLines,
            highlightLines: m.highlightLines.length ? m.highlightLines : page.lines,
            bandReliable: m.bandReliable,
            matchType: m.matchType,
            matchNote: m.matchNote,
          };
        }
        if (best.similarity >= 0.999 && best.matchType === 'line-exact') break;
      }
    } else if (!best.snippet) {
      const page = ocrPages.find(p => p.file === best.file);
      if (page?.lines?.length) {
        best.snippet = page.lines.join(' ').trim();
        best.highlightLines = page.lines;
        best.totalLines = page.lines.length;
      }
    }

    let issueNote = best.matchNote || '';
    const displayFile = isLoadingKey
      ? (best.file || loadingDisplayFile(item.key, loadingFiles) || loadingFiles[0] || '')
      : '';

    if (isLoadingKey) {
      if (best.similarity < PASS_THRESHOLD) {
        const searched = crossMatched ? loadingPagesForMatch.length : keyFiles.length;
        issueNote = `Loading 截圖未找到相符文案（已搜 ${searched} 張${crossMatched ? '，含跨張配對' : ''}）`;
      } else if (crossMatched && best.file && best.file !== loadingDisplayFile(item.key, loadingFiles)) {
        issueNote = `跨張配對：文案命中於 ${best.file}`;
      } else if (!crossMatched && best.file && displayFile && best.file !== displayFile) {
        issueNote = `文案命中於 ${best.file}（預覽為 ${displayFile}）`;
      }
    } else if (itemIsBuyKey) {
      if (best.similarity < PASS_THRESHOLD) {
        issueNote = issueNote || `Buy 彈窗圖未找到相符文案（已搜 ${buyFiles.length} 張 buy_*.png）`;
      }
    } else if (best.similarity < PASS_THRESHOLD) {
      const infoFiles = infoCaptureFiles(files);
      issueNote = issueNote || `Info 捲動圖未找到相符文案（已搜 ${infoFiles.length} 張 info_scroll_*.png）`;
      if (best.file && best.snippet) {
        issueNote += `；最接近命中於 ${best.file}`;
      }
    }

    results.push({
      key: item.key,
      expected: item.expectedText,
      similarity: best.similarity,
      status: statusOf(best.similarity),
      sourceFile: isLoadingKey
        ? (best.file || loadingFiles[0] || '')
        : itemIsBuyKey
          ? (best.file || buyFiles[0] || '')
          : (best.file || ''),
      displayFile: displayFile || undefined,
      snippet: best.snippet,
      lineStart: best.lineStart,
      lineEnd: best.lineEnd,
      totalLines: best.totalLines,
      highlightLines: best.highlightLines,
      issueNote,
      isLoadingKey,
      isBuyKey: itemIsBuyKey,
    });
  }

  const summary = results.reduce(
    (acc, r) => ((acc[r.status] = (acc[r.status] || 0) + 1), acc),
    { PASS: 0, REVIEW: 0, FAIL: 0 }
  );
  return { results, summary };
}

async function listPngs(dir) {
  let names;
  try {
    names = await fs.readdir(dir);
  } catch {
    return null;
  }
  return names
    .filter(n => /\.png$/i.test(n))
    .sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
}

/**
 * 強制重 OCR 單張來源圖，更新快取後重新比對整個工作表。
 */
export async function reOcrSourceFile({
  imagesDir,
  sourceFile,
  items,
  provider = PROVIDER_GEMINI,
  apiKey,
  modelId,
  verifyOpts,
  onLog = () => {},
}) {
  const forceSet = new Set([sourceFile]);
  return verifySlot({
    imagesDir,
    items,
    provider,
    apiKey,
    modelId,
    forceOcr: false,
    forceOcrFiles: forceSet,
    verifyOpts,
    onLog,
  });
}

/**
 * 手動貼圖：對單張截圖 OCR 並與指定 key 預期文案比對（同 l10n-text-verify 流程）。
 */
export async function verifyPastedKey({
  key,
  expectedText,
  imageBuffer,
  mimeType = 'image/png',
  provider = PROVIDER_GEMINI,
  apiKey,
  modelId,
  verifyOpts,
}) {
  const vOpts = await resolveVerifyOpts(verifyOpts);
  const tokenUsage = createUsageAccumulator();
  const prepareOpts = { maxWidth: vOpts.ocrMaxWidth, jpegQuality: vOpts.ocrJpegQuality };
  const { buffer, mimeType: outMime } = await prepareOcrBuffer(imageBuffer, prepareOpts);
  const text = await ocrImage({
    provider,
    apiKey,
    modelId,
    buffer,
    mimeType: outMime,
    maxOutputTokens: vOpts.maxOutputTokens,
    usageAcc: tokenUsage,
  });
  const lines = textToLines(text);
  const m = findBestMatch(expectedText, lines);
  const isLoadingKey = /^Loading_\d+$/i.test(key);

  return {
    key,
    expected: expectedText,
    similarity: m.similarity,
    status: statusOf(m.similarity),
    sourceFile: '',
    manualPaste: true,
    snippet: m.snippet,
    lineStart: m.lineStart,
    lineEnd: m.lineEnd,
    totalLines: m.totalLines,
    highlightLines: m.highlightLines,
    issueNote: m.matchNote || '手動貼圖比對',
    isLoadingKey,
    tokenUsage,
  };
}
