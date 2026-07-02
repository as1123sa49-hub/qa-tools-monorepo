import fs from 'node:fs/promises';
import path from 'node:path';
import { resolveTemplateClickCandidate } from './template-click.js';
import { loadCaptureMetaFromDir, saveCaptureMeta } from './capture-meta.js';
import { saveDebug } from './capture-debug.js';
import { portraitBuyBonusStrategies } from './portrait-layout.js';
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

async function buildLandscapeBuyCandidates(page, cfg, templatesDir, { slotId, captureMeta }, onLog) {
  const { candidates, add } = createCandidateCollector();

  await addLearnedCandidate(add, page, captureMeta?.buyBonusClick);

  const overrides = slotId ? cfg.buyBonus?.slotOverrides?.[slotId] : null;
  if (overrides?.landscapeCandidates) {
    for (const pos of overrides.landscapeCandidates) {
      await add(pos.x, pos.y, pos.note || '手動覆寫');
    }
  }
  if (overrides?.landscapeFractions) {
    for (const f of overrides.landscapeFractions) {
      const pt = await pagePointFromFraction(page, f.fx, f.fy);
      if (pt) await add(pt.pageX, pt.pageY, f.note || '手動覆寫', pt.fx, pt.fy);
    }
  }

  if (!overrides?.skipTemplates && cfg.templates?.buy_bonus_btn) {
    const tpl = await resolveTemplateClickCandidate(
      page, cfg, templatesDir, 'buy_bonus_btn', cfg.searchRegions?.buy_bonus_btn, onLog,
    );
    if (tpl) await add(tpl.pageX, tpl.pageY, tpl.note, tpl.fx, tpl.fy);
  }

  const buyCfg = cfg.buyBonus || {};
  const fx = buyCfg.landscapeFx ?? 0.12;
  const fyList = buyCfg.landscapeFySweep ?? [0.13, 0.22, 0.35, 0.50, 0.65, 0.75];
  for (const fy of fyList) {
    const pt = await pagePointFromFraction(page, fx, fy);
    if (pt) await add(pt.pageX, pt.pageY, `左側掃描 fy=${fy}`, pt.fx, pt.fy);
  }

  const cc = cfg.canvasClicks?.buy_bonus_btn;
  if (cc) await add(cc.x, cc.y, 'canvasClicks 預設');

  return candidates;
}

async function buildPortraitBuyCandidates(page, cfg, templatesDir, activeRegion, captureMeta) {
  const { candidates, add } = createCandidateCollector();

  await addLearnedCandidate(add, page, captureMeta?.buyBonusClick);

  for (const s of portraitBuyBonusStrategies(cfg, activeRegion)) {
    if (s.kind === 'fraction') {
      const pt = await pagePointFromFraction(page, s.fx, s.fy);
      if (pt) await add(pt.pageX, pt.pageY, s.note || '直版比例', pt.fx, pt.fy);
    }
  }

  if (cfg.templates?.buy_bonus_btn) {
    const region = cfg.searchRegions?.buy_bonus_btn_portrait || cfg.searchRegions?.buy_bonus_btn;
    const tpl = await resolveTemplateClickCandidate(page, cfg, templatesDir, 'buy_bonus_btn', region, () => {});
    if (tpl) await add(tpl.pageX, tpl.pageY, tpl.note, tpl.fx, tpl.fy);
  }

  return candidates;
}

function measureBuyPopupOpened(before, after, cfg) {
  const region = cfg.buyBonus?.popupVerifyRegion ?? null;
  return diffRatio(before, after, region);
}

/**
 * 逐候選點擊 Buy Bonus，以彈窗畫面變化驗證；成功則寫入 capture-meta.buyBonusClick。
 */
export async function tryOpenBuyBonusPopup(page, cfg, templatesDir, onLog, {
  portraitLayout,
  activeRegion,
  slotId,
  outDir,
  before,
  openWaitMs,
  popupThreshold,
}) {
  const captureMeta = await loadCaptureMetaFromDir(outDir);
  const candidates = portraitLayout
    ? await buildPortraitBuyCandidates(page, cfg, templatesDir, activeRegion, captureMeta)
    : await buildLandscapeBuyCandidates(page, cfg, templatesDir, { slotId, captureMeta }, onLog);

  if (!candidates.length) {
    return { opened: false, lastRatio: 0 };
  }

  const source = captureMeta?.buyBonusClick ? '（含快取）' : '';
  onLog?.(`  Buy 候選 ${candidates.length} 個${source}，逐點驗證彈窗`);

  const result = await tryClickCandidates(page, candidates, {
    threshold: popupThreshold,
    onLog,
    getBefore: async () => before,
    click: async (c) => {
      await waitForUnityCanvas(page);
      await clickCanvasPoint(page, c.pageX, c.pageY, { delay: 80 });
      const note = c.note ? ` ${c.note}` : '';
      onLog?.(`  [buy_bonus_btn] 點擊 (${c.pageX}, ${c.pageY})${note}`);
    },
    waitAfterClick: async (p) => {
      await p.waitForTimeout(openWaitMs);
    },
    getAfter: async (p) => screenshotBuffer(p),
    measureRatio: async (b, a) => measureBuyPopupOpened(b, a, cfg),
    formatAttemptLog: (_c, ratio, threshold) =>
      `  Buy 彈窗變化 ${(ratio * 100).toFixed(1)}%（門檻 ${(threshold * 100).toFixed(0)}%）`,
    formatSuccessLog: (c) => `  ✓ Buy 彈窗已開啟，已記憶座標 (${c.pageX}, ${c.pageY})`,
    formatFailLog: (_c, i, total) => `  未開啟彈窗，換下一候選 (${i + 1}/${total})`,
    onCacheMiss: async () => {
      await saveCaptureMeta(outDir, { buyBonusClick: null });
      onLog?.('  快取座標未開啟彈窗，已清除');
    },
  });

  if (result.success && result.candidate) {
    await saveCaptureMeta(outDir, {
      buyBonusClick: await buildLearnedClick(page, result.candidate),
    });
    return { opened: true, after: result.after, lastRatio: result.lastRatio };
  }

  return { opened: false, lastRatio: result.lastRatio };
}

/**
 * 點擊 Buy Bonus → 截彈窗 → 關閉。
 * closeOverlay 由 capture-flow 注入，避免與 info UI 模組循環依賴。
 */
export async function captureBuyBonus(page, cfg, outDir, templatesDir, onLog, {
  portraitLayout = false,
  activeRegion,
  slotId,
  closeOverlay,
} = {}) {
  const buyCfg = cfg.buyBonus || {};
  if (buyCfg.enabled === false) {
    onLog?.('  Buy Bonus 擷取已停用（buyBonus.enabled=false）');
    return { files: [], opened: false };
  }

  const optional = buyCfg.optional !== false;
  const openWaitMs = buyCfg.openWaitMs ?? 1200;
  const popupThreshold = buyCfg.popupChangeThreshold ?? 0.08;
  const outFile = buyCfg.outputFile || 'buy_popup.png';
  const outPath = path.join(outDir, outFile);

  if (!/^buy_/i.test(outFile)) {
    onLog?.(`  ⚠ buyBonus.outputFile 建議使用 buy_*.png（目前：${outFile}）`);
  }

  await waitForUnityCanvas(page);
  await saveDebug(page, cfg, 'before_buy_bonus_btn', onLog);
  const before = await screenshotBuffer(page);

  try {
    onLog?.('  點擊 Buy Bonus');
    const { opened, after: afterOpen, lastRatio } = await tryOpenBuyBonusPopup(page, cfg, templatesDir, onLog, {
      portraitLayout,
      activeRegion,
      slotId,
      outDir,
      before,
      openWaitMs,
      popupThreshold,
    });

    await saveDebug(page, cfg, 'buy_popup_open', onLog);

    if (!opened) {
      const msg = '點擊後畫面變化不足，可能未開啟 Buy 彈窗（按鈕位置或狀態不符）';
      if (optional) {
        onLog?.(`  ⚠ ${msg}${lastRatio != null ? `（最後 ${(lastRatio * 100).toFixed(1)}%）` : ''}`);
        return { files: [], opened: false };
      }
      throw new Error(msg);
    }

    await fs.writeFile(outPath, afterOpen);
    onLog?.(`  已截 ${outFile}`);

    onLog?.('  關閉 Buy 彈窗');
    await closeOverlay?.(page, cfg, templatesDir, onLog, {
      portraitLayout,
      key: cfg.templates?.buy_bonus_close ? 'buy_bonus_close' : 'info_close_x',
      activeRegion,
    });
    await page.waitForTimeout(1000);
    await saveDebug(page, cfg, 'buy_popup_closed', onLog);

    return { files: [outPath], opened: true };
  } catch (err) {
    if (optional) {
      onLog?.(`  ⚠ Buy Bonus 擷取失敗（略過）：${err.message}`);
      return { files: [], opened: false };
    }
    throw err;
  }
}
