import express from 'express';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { runSlotCapture, loadConfig, outputDir } from './lib/capture-flow.js';
import { slotToSheet } from './lib/slot-sheet.js';
import { loadKeysFromSheet } from './lib/xlsx-node.js';
import { verifySlot, verifyPastedKey, reOcrSourceFile } from './lib/verify.js';
import { sumVerifyReports, formatUsageSummary } from './lib/usage-summary.js';
import { PROVIDER_SIRAYA, getApiKeyLabel } from './lib/llm-providers.js';
import { resolveUserIdFromRequest, userOutputRoot } from './lib/user-context.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const app = express();
const PORT = process.env.PORT || 3847;

app.use(express.json({ limit: '100mb' }));
app.use(express.static(path.join(__dirname, 'public')));

/** @type {Map<string, { abortController: AbortController, running: boolean }>} */
const captureByUser = new Map();
/** @type {Map<string, { abortController: AbortController, running: boolean }>} */
const verifyByUser = new Map();

function getUserJob(map, userId) {
  return map.get(userId);
}

function abortUserJob(map, userId) {
  const job = map.get(userId);
  if (job?.abortController) job.abortController.abort();
}

function setUserJob(map, userId, job) {
  map.set(userId, job);
}

function clearUserJob(map, userId, ac) {
  const job = map.get(userId);
  if (job?.abortController === ac) map.delete(userId);
}

function bindClientAbort(req, res, onAbort) {
  const disconnect = () => {
    if (!res.writableFinished) onAbort();
  };
  req.on('aborted', disconnect);
  res.on('close', disconnect);
}

function ndjsonWrite(res, obj, isAborted = () => false) {
  if (isAborted() || res.writableEnded) return;
  try {
    res.write(`${JSON.stringify(obj)}\n`);
  } catch {
    /* client gone */
  }
}

app.get('/api/status', (req, res) => {
  const userId = resolveUserIdFromRequest(req);
  const cap = getUserJob(captureByUser, userId);
  const ver = getUserJob(verifyByUser, userId);
  res.json({
    userId,
    running: cap?.running ?? false,
    verifying: ver?.running ?? false,
  });
});

app.get('/api/lang-map', async (_req, res) => {
  try {
    const cfg = await loadConfig();
    res.json(cfg.langMap || {});
  } catch (err) {
    res.status(500).json({ error: String(err.message || err) });
  }
});

app.post('/api/capture', async (req, res) => {
  const userId = resolveUserIdFromRequest(req);
  abortUserJob(captureByUser, userId);

  const { env = 'uat', lang, langs: langsBody, slots = ['Slot015'], sheetName } = req.body || {};
  const slotList = Array.isArray(slots) ? slots : String(slots).split(',').map(s => s.trim()).filter(Boolean);

  if (!slotList.length) {
    return res.status(400).json({ error: '請指定至少一個 Slot' });
  }

  const cfg = await loadConfig();
  let langList = Array.isArray(langsBody)
    ? langsBody
    : typeof langsBody === 'string'
      ? langsBody.split(',').map(s => s.trim()).filter(Boolean)
      : lang
        ? [lang]
        : ['bn'];
  langList = [...new Set(langList.map(s => String(s).trim()).filter(Boolean))];
  if (!langList.length) {
    return res.status(400).json({ error: '請指定至少一個語系' });
  }

  const notCaptureable = langList.filter(code => !cfg.langMap?.[code]?.portalLabel);
  if (notCaptureable.length) {
    return res.status(400).json({
      error: `以下語系無法擷取（請在 config.json langMap 補 portalLabel）：${notCaptureable.join(', ')}`,
    });
  }

  const ac = new AbortController();
  setUserJob(captureByUser, userId, { abortController: ac, running: true });
  bindClientAbort(req, res, () => {
    ac.abort();
    const job = getUserJob(captureByUser, userId);
    if (job?.abortController === ac) job.running = false;
    clearUserJob(captureByUser, userId, ac);
  });

  res.setHeader('Content-Type', 'application/x-ndjson');
  res.setHeader('Cache-Control', 'no-cache');
  res.flushHeaders?.();

  const write = obj => {
    ndjsonWrite(res, obj, () => ac.signal.aborted);
  };

  const results = [];

  try {
    const continueOnSlotError = cfg.continueOnSlotError !== false;
    for (const slotId of slotList) {
      if (ac.signal.aborted) break;
      const sheet = sheetName || slotToSheet(slotId);
      for (const langCode of langList) {
        if (ac.signal.aborted) break;
        write({ type: 'log', message: `開始 ${slotId} / ${langCode}（工作表 ${sheet}）` });
        const result = await runSlotCapture({
          env,
          lang: langCode,
          slotId,
          sheetName: sheet,
          userId,
          continueOnError: continueOnSlotError,
          onLog: msg => write({ type: 'log', message: msg }),
        });
        results.push({ ...result, lang: langCode });
        if (result.ok) {
          write({ type: 'done', slotId, lang: langCode, outDir: result.outDir, files: result.files });
        } else {
          const errMsg = result.errors[0] || '擷取失敗';
          write({
            type: 'slot-error',
            slotId,
            lang: langCode,
            outDir: result.outDir,
            files: result.files,
            message: errMsg,
          });
        }
      }
    }
    if (!ac.signal.aborted) {
      const failed = results.filter(r => r.ok === false);
      write({
        type: 'complete',
        results,
        failedCount: failed.length,
        okCount: results.length - failed.length,
      });
    }
  } catch (err) {
    if (!ac.signal.aborted) write({ type: 'error', message: String(err.message || err) });
  } finally {
    const job = getUserJob(captureByUser, userId);
    if (job?.abortController === ac) job.running = false;
    clearUserJob(captureByUser, userId, ac);
    if (!res.writableEnded) res.end();
  }
});

app.post('/api/verify', async (req, res) => {
  const userId = resolveUserIdFromRequest(req);
  abortUserJob(verifyByUser, userId);

  const {
    env = 'uat',
    lang,
    langs: langsBody,
    slots = [],
    sheetName,
    xlsxBase64,
    provider = 'gemini',
    apiKey,
    modelId = 'gemini-2.5-flash',
    forceOcr = false,
  } = req.body || {};

  const llmProvider = provider === PROVIDER_SIRAYA ? PROVIDER_SIRAYA : 'gemini';

  const slotList = Array.isArray(slots)
    ? slots
    : String(slots).split(',').map(s => s.trim()).filter(Boolean);

  if (!slotList.length) return res.status(400).json({ error: '請指定至少一個 Slot' });
  if (!apiKey) return res.status(400).json({ error: `缺少 ${getApiKeyLabel(llmProvider)}` });
  if (!xlsxBase64) return res.status(400).json({ error: '缺少翻譯表（XLSX）' });

  let langList = Array.isArray(langsBody)
    ? langsBody
    : typeof langsBody === 'string'
      ? langsBody.split(',').map(s => s.trim()).filter(Boolean)
      : lang
        ? [lang]
        : ['bn'];
  langList = [...new Set(langList.map(s => String(s).trim()).filter(Boolean))];
  if (!langList.length) return res.status(400).json({ error: '請指定至少一個語系' });

  const ac = new AbortController();
  setUserJob(verifyByUser, userId, { abortController: ac, running: true });
  bindClientAbort(req, res, () => {
    ac.abort();
    const job = getUserJob(verifyByUser, userId);
    if (job?.abortController === ac) job.running = false;
    clearUserJob(verifyByUser, userId, ac);
  });

  res.setHeader('Content-Type', 'application/x-ndjson');
  res.setHeader('Cache-Control', 'no-cache');
  res.flushHeaders?.();
  const write = obj => ndjsonWrite(res, obj, () => ac.signal.aborted);

  try {
    const cfg = await loadConfig();
    const buffer = Buffer.from(xlsxBase64, 'base64');
    const reports = [];

    for (const slotId of slotList) {
      if (ac.signal.aborted) break;
      const sheet = sheetName || slotToSheet(slotId);
      for (const langCode of langList) {
        if (ac.signal.aborted) break;
        write({ type: 'log', message: `驗證 ${slotId} / ${langCode}（工作表 ${sheet} / ${llmProvider}）` });

        try {
          const { items } = await loadKeysFromSheet(buffer, sheet, langCode);
          if (!items.length) {
            write({ type: 'log', message: `  ⚠ 工作表 ${sheet} 無 ${langCode} 字串，略過` });
            continue;
          }
          write({ type: 'log', message: `  ${items.length} 個 key，開始 OCR…` });

          const imagesDir = outputDir(cfg, env, langCode, slotId, userId);
          const report = await verifySlot({
            imagesDir,
            items,
            provider: llmProvider,
            apiKey,
            modelId,
            forceOcr: Boolean(forceOcr),
            signal: ac.signal,
            onLog: msg => write({ type: 'log', message: msg }),
          });
          if (report.aborted) break;
          const s = report.summary;
          const tu = report.tokenUsage;
          const tokenPart = tu?.totalTokens
            ? ` · token ${tu.promptTokens} in / ${tu.completionTokens} out${tu.apiCostReported ? ` · $${tu.costUsd.toFixed(4)}` : ''}`
            : '';
          write({
            type: 'log',
            message: `  完成：OCR API ${report.ocrApiCalls ?? report.ocrCount} 次 / ${report.ocrCount} 頁（快取 ${report.cacheHits}${report.scrollDeduped ? `、去重 ${report.scrollDeduped}` : ''}）· PASS ${s.PASS} / REVIEW ${s.REVIEW} / FAIL ${s.FAIL}${tokenPart}`,
          });
          write({ type: 'slot-done', slotId, sheet, env, lang: langCode, ...report });
          reports.push({ slotId, sheet, env, lang: langCode, ...report });
        } catch (err) {
          write({ type: 'log', message: `  ✗ ${slotId} / ${langCode}：${String(err.message || err)}` });
        }
      }
    }

    if (!ac.signal.aborted) {
      const usageSummary = sumVerifyReports(reports);
      const summaryLine = formatUsageSummary(usageSummary);
      if (summaryLine) {
        write({ type: 'log', message: `── 本次用量 ── ${summaryLine}` });
      }
      write({ type: 'complete', reports, usageSummary });
    }
  } catch (err) {
    if (!ac.signal.aborted) write({ type: 'error', message: String(err.message || err) });
  } finally {
    const job = getUserJob(verifyByUser, userId);
    if (job?.abortController === ac) job.running = false;
    clearUserJob(verifyByUser, userId, ac);
    if (!res.writableEnded) res.end();
  }
});

/** 重 OCR 單張來源圖，更新快取並重新比對整個工作表 */
app.post('/api/verify-reocr', async (req, res) => {
  const {
    env = 'uat',
    lang = 'bn',
    slotId,
    sheetName,
    sourceFile,
    xlsxBase64,
    provider = 'gemini',
    apiKey,
    modelId = 'gemini-2.5-flash',
  } = req.body || {};

  const llmProvider = provider === PROVIDER_SIRAYA ? PROVIDER_SIRAYA : 'gemini';

  if (!slotId) return res.status(400).json({ error: '請指定 Slot' });
  if (!sourceFile || !/\.png$/i.test(sourceFile)) {
    return res.status(400).json({ error: '請指定有效的來源圖檔名（*.png）' });
  }
  if (!xlsxBase64) return res.status(400).json({ error: '缺少翻譯表（XLSX）' });
  if (!apiKey) return res.status(400).json({ error: `缺少 ${getApiKeyLabel(llmProvider)}` });

  const userId = resolveUserIdFromRequest(req);

  try {
    const cfg = await loadConfig();
    const buffer = Buffer.from(xlsxBase64, 'base64');
    const sheet = sheetName || slotToSheet(slotId);
    const { items } = await loadKeysFromSheet(buffer, sheet, lang);
    if (!items.length) {
      return res.status(400).json({ error: `工作表 ${sheet} 無 ${lang} 字串` });
    }

    const imagesDir = outputDir(cfg, env, lang, slotId, userId);
    const report = await reOcrSourceFile({
      imagesDir,
      sourceFile,
      items,
      provider: llmProvider,
      apiKey,
      modelId,
      onLog: msg => console.log(`[reocr ${slotId}] ${msg}`),
    });

    const { tokenUsage, ...rest } = report;
    res.json({
      slotId,
      sheet,
      env,
      lang,
      sourceFile,
      ...rest,
      tokenUsage,
    });
  } catch (err) {
    res.status(500).json({ error: String(err.message || err) });
  }
});

/** 手動貼圖：對單一 key 的截圖做 OCR 比對（同 l10n-text-verify） */
app.post('/api/verify-paste', async (req, res) => {
  const {
    key,
    expectedText,
    imageBase64,
    mimeType = 'image/png',
    provider = 'gemini',
    apiKey,
    modelId = 'gemini-2.5-flash',
  } = req.body || {};

  const llmProvider = provider === PROVIDER_SIRAYA ? PROVIDER_SIRAYA : 'gemini';

  if (!key || !String(key).trim()) {
    return res.status(400).json({ error: '請指定 Key' });
  }
  if (expectedText == null) {
    return res.status(400).json({ error: '缺少預期文案' });
  }
  if (!imageBase64) return res.status(400).json({ error: '缺少截圖' });
  if (!apiKey) return res.status(400).json({ error: `缺少 ${getApiKeyLabel(llmProvider)}` });

  try {
    const imageBuffer = Buffer.from(imageBase64, 'base64');
    if (!imageBuffer.length) return res.status(400).json({ error: '截圖資料無效' });

    const result = await verifyPastedKey({
      key: String(key).trim(),
      expectedText: String(expectedText),
      imageBuffer,
      mimeType: String(mimeType || 'image/png'),
      provider: llmProvider,
      apiKey,
      modelId,
    });
    const { tokenUsage, ...row } = result;
    res.json({ result: row, tokenUsage });
  } catch (err) {
    res.status(500).json({ error: String(err.message || err) });
  }
});

/** 與 xlsx 語系代碼一致：bn、ja-JP、zh-Hant、es-ES 等 */
function isValidLangParam(lang) {
  return /^[a-zA-Z]{2,12}(-[a-zA-Z0-9]{2,12})*$/.test(lang);
}

/** 提供驗證結果預覽用的截圖（僅限 captures 目錄內 PNG） */
app.get('/api/captures/:env/:lang/:slotId/:file', async (req, res) => {
  const { env, lang, slotId, file } = req.params;
  if (!/^[a-z0-9_-]+$/i.test(env) || !isValidLangParam(lang)) {
    return res.status(400).send('invalid path');
  }
  if (!/^Slot\d+$/i.test(slotId)) return res.status(400).send('invalid slot');
  if (!/^[a-z0-9_.-]+\.png$/i.test(file) || file.includes('..')) {
    return res.status(400).send('invalid file');
  }
  try {
    const cfg = await loadConfig();
    const userId = resolveUserIdFromRequest(req);
    const filePath = path.join(outputDir(cfg, env, lang, slotId, userId), file);
    const root = path.resolve(userOutputRoot(userId, cfg));
    const resolved = path.resolve(filePath);
    if (!resolved.startsWith(root)) return res.status(403).send('forbidden');
    res.sendFile(resolved);
  } catch {
    res.status(404).send('not found');
  }
});

app.listen(PORT, () => {
  console.log(`l10n-capture UI: http://localhost:${PORT}`);
});
