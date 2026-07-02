import { resolveTemplateClickCandidate } from './template-click.js';
import { loadCaptureMetaFromDir, saveCaptureMeta } from './capture-meta.js';
import { saveDebug } from './capture-debug.js';
import {
  waitForUnityCanvas,
  clickCanvasPoint,
  screenshotBuffer,
  diffRatio,
} from './browser-utils.js';
import {
  pagePointFromFraction,
  createCandidateCollector,
  tryClickCandidates,
  addLearnedCandidate,
  buildLearnedClick,
} from './click-strategies.js';

/** 依 continueCandidates 的 x 座標排序：置中優先，直版時略過偏右候選 */
export function orderContinueCandidates(candidates, portraitLayout) {
  const center = [];
  const landscape = [];
  const rest = [];
  for (const c of candidates) {
    if (!c || !Number.isFinite(c.x) || !Number.isFinite(c.y)) continue;
    if (c.x >= 800 && c.x <= 1120) center.push(c);
    else if (c.x > 1200) landscape.push(c);
    else rest.push(c);
  }
  if (portraitLayout) return [...center, ...rest];
  return [...center, ...landscape, ...rest];
}

function continueSearchRegion(cfg, activeRegion) {
  if (!activeRegion?.width) return cfg.searchRegions?.continue_btn ?? null;
  const vpH = cfg.viewport?.height ?? 911;
  const top = Math.max(
    activeRegion.top + Math.round(activeRegion.height * 0.55),
    vpH - 200,
  );
  return {
    left: activeRegion.left,
    top,
    width: activeRegion.width,
    height: Math.min(vpH - top, 200),
  };
}

function continuePointFromRegion(activeRegion, viewport = { width: 1920, height: 911 }) {
  const vpH = viewport.height ?? 911;
  return {
    x: activeRegion.left + Math.round(activeRegion.width / 2),
    y: Math.round(vpH * 0.85),
    note: '輪播區 X 置中 + 畫面底部',
  };
}

/** 組裝 Continue 候選（快取 → 覆寫 → 輪播區 → 模板 → 比例 → 座標） */
export async function buildContinueCandidates(page, cfg, templatesDir, {
  portraitLayout, activeRegion, captureMeta, slotId,
}, onLog) {
  const { candidates, add } = createCandidateCollector();

  await addLearnedCandidate(add, page, captureMeta?.continueClick);

  const overrides = slotId ? cfg.continue?.slotOverrides?.[slotId] : null;
  if (overrides?.candidates) {
    for (const pos of overrides.candidates) {
      await add(pos.x, pos.y, pos.note || '手動覆寫');
    }
  }
  if (overrides?.fractions) {
    for (const f of overrides.fractions) {
      const pt = await pagePointFromFraction(page, f.fx, f.fy);
      if (pt) await add(pt.pageX, pt.pageY, f.note || '手動覆寫', pt.fx, pt.fy);
    }
  }

  if (activeRegion?.width) {
    const p = continuePointFromRegion(activeRegion, cfg.viewport);
    await add(p.x, p.y, p.note);
  }

  if (!overrides?.skipTemplates && cfg.templates?.continue_btn) {
    const tpl = await resolveTemplateClickCandidate(
      page, cfg, templatesDir, 'continue_btn', continueSearchRegion(cfg, activeRegion), onLog,
    );
    if (tpl) await add(tpl.pageX, tpl.pageY, tpl.note, tpl.fx, tpl.fy);
  }

  const fractions = cfg.continueCanvasFractions ?? [
    { fx: 0.5, fy: 0.89, note: 'canvas 置中底部' },
    { fx: 0.5, fy: 0.92, note: 'canvas 底部備援' },
  ];
  for (const f of fractions) {
    if (Number.isFinite(f.fx) && Number.isFinite(f.fy)) {
      const pt = await pagePointFromFraction(page, f.fx, f.fy);
      if (pt) await add(pt.pageX, pt.pageY, f.note || '比例', pt.fx, pt.fy);
    }
  }

  const rawCandidates = Array.isArray(cfg.continueCandidates) && cfg.continueCandidates.length
    ? cfg.continueCandidates
    : [cfg.canvasClicks?.continue_btn].filter(Boolean);
  for (const pos of orderContinueCandidates(rawCandidates, portraitLayout)) {
    await add(pos.x, pos.y, pos.note || '候選座標');
  }

  return candidates;
}

/** 依序嘗試多個繼續鍵候選；成功則寫入 capture-meta.continueClick */
export async function clickContinue(page, cfg, templatesDir, onLog, {
  portraitLayout = false,
  activeRegion = null,
  outDir = null,
  slotId = null,
} = {}) {
  const enterThreshold = cfg.continueEnterThreshold ?? 0.3;
  const settleMs = cfg.continueSettleMs ?? 1500;

  await page.waitForTimeout(settleMs);
  onLog?.(`  等待輪播停穩 ${settleMs}ms`);

  const captureMeta = outDir ? await loadCaptureMetaFromDir(outDir) : null;
  const candidates = await buildContinueCandidates(page, cfg, templatesDir, {
    portraitLayout, activeRegion, captureMeta, slotId,
  }, onLog);

  if (!candidates.length) {
    throw new Error('未設定繼續鍵候選（continueCandidates 或 canvasClicks.continue_btn）');
  }

  const source = captureMeta?.continueClick ? '（含快取）' : '';
  onLog?.(`  Continue 候選 ${candidates.length} 個${source}，逐點驗證進入遊戲`);

  let attemptIndex = 0;
  const result = await tryClickCandidates(page, candidates, {
    threshold: enterThreshold,
    onLog,
    getBefore: async () => screenshotBuffer(page),
    click: async (c) => {
      await waitForUnityCanvas(page);
      await clickCanvasPoint(page, c.pageX, c.pageY, { delay: 80 });
      const note = c.note ? ` ${c.note}` : '';
      onLog?.(`  [continue_btn] 點擊 (${c.pageX}, ${c.pageY})${note}`);
    },
    waitAfterClick: async (p) => {
      await p.waitForTimeout(cfg.timeouts.mainGameMs ?? 3500);
      await saveDebug(p, cfg, `after_continue_try${++attemptIndex}`, onLog);
    },
    getAfter: async (p) => screenshotBuffer(p),
    measureRatio: async (before, after) => diffRatio(before, after),
    formatAttemptLog: (_c, ratio, threshold) =>
      `  繼續點擊 畫面變化 ${(ratio * 100).toFixed(1)}%（需 ≥ ${(threshold * 100).toFixed(0)}%）`,
    formatSuccessLog: (c) => outDir
      ? `  ✓ 已進入主遊戲，已記憶座標 (${c.pageX}, ${c.pageY})`
      : '  已進入主遊戲',
    formatFailLog: (_c, i, total) => `  變化不足，換下一候選 (${i + 1}/${total})`,
    onCacheMiss: async () => {
      if (outDir) {
        await saveCaptureMeta(outDir, { continueClick: null });
        onLog?.('  快取座標未進入遊戲，已清除');
      }
    },
  });

  if (result.success) {
    if (outDir && result.candidate) {
      await saveCaptureMeta(outDir, {
        continueClick: await buildLearnedClick(page, result.candidate),
      });
    }
    return;
  }

  throw new Error(
    '點擊繼續後畫面變化不足，可能未進入主遊戲（已試所有 Continue 候選）',
  );
}
