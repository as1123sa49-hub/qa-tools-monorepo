import fs from 'node:fs/promises';
import path from 'node:path';
import { chromium } from 'playwright';
import { promoTextRegionForCapture } from './loading-promo-region.js';
import {
  loadConfig,
  outputDir,
  TOOL_ROOT,
  windowArgs,
  forceWindowBounds,
} from './config.js';
import { saveCaptureMeta } from './capture-meta.js';
import { ensureDir } from './browser-utils.js';
import { prepareLobby, enterSlotWithLangCheck } from './lobby-flow.js';
import { captureLoading } from './loading-capture.js';
import { clickContinue } from './continue-click.js';
import { captureBuyBonus } from './buy-bonus-capture.js';
import { mergePortraitFractions } from './portrait-layout.js';
import {
  captureInfoScroll,
  closeTopRightOverlay,
  returnToLobby,
} from './info-capture.js';

/**
 * @param {object} opts
 * @param {string} opts.env
 * @param {string} opts.lang
 * @param {string} opts.slotId
 * @param {string} [opts.sheetName]
 * @param {function} [opts.onLog]
 * @param {boolean} [opts.continueOnError] 失敗時回傳 partial result 不 throw（整批繼續下一款）
 */
export async function runSlotCapture(opts) {
  const cfg = await loadConfig();
  const continueOnError = opts.continueOnError ?? cfg.continueOnSlotError !== false;
  const templatesDir = path.join(TOOL_ROOT, 'templates', 'game');
  const authPath = path.join(TOOL_ROOT, cfg.authFile);
  const onLog = opts.onLog || (() => {});

  const browser = await chromium.launch({
    headless: false,
    args: windowArgs(cfg),
  });
  const context = await browser.newContext({
    viewport: cfg.viewport,
    storageState: (await fs.stat(authPath).catch(() => null)) ? authPath : undefined,
  });
  const page = await context.newPage();
  await forceWindowBounds(page, cfg);

  const outDir = outputDir(cfg, opts.env, opts.lang, opts.slotId);
  await ensureDir(outDir);
  cfg._outDir = outDir;

  const result = { slotId: opts.slotId, sheetName: opts.sheetName, outDir, files: [], errors: [], ok: true };

  try {
    onLog(`準備大廳 ${opts.env} / ${opts.lang}`);
    await prepareLobby(page, cfg, opts.env, opts.lang);

    onLog(`搜尋並進入 ${opts.slotId}`);
    await enterSlotWithLangCheck(page, cfg, opts.env, opts.lang, opts.slotId, onLog);

    onLog('擷取 Loading 畫面');
    const { files: loadingFiles, portraitLayout, activeRegion } = await captureLoading(
      page, cfg, outDir, templatesDir, onLog,
    );
    result.files.push(...loadingFiles);
    await saveCaptureMeta(outDir, {
      loadingPromoRegion: activeRegion,
      promoTextRegion: promoTextRegionForCapture(cfg, portraitLayout, activeRegion),
      portraitLayout,
    });
    if (portraitLayout && activeRegion) {
      const ui = mergePortraitFractions(cfg, activeRegion);
      onLog?.(
        `  直版置中區 [${activeRegion.left},${activeRegion.top} ${activeRegion.width}x${activeRegion.height}]` +
        ` → info (${ui.info_icon?.fx?.toFixed(2)}, ${ui.info_icon?.fy?.toFixed(2)})`,
      );
    }

    onLog('點擊繼續進入主遊戲');
    await clickContinue(page, cfg, templatesDir, onLog, {
      portraitLayout,
      activeRegion,
      outDir,
      slotId: opts.slotId,
    });

    onLog('Buy Bonus 彈窗擷取');
    const buyResult = await captureBuyBonus(page, cfg, outDir, templatesDir, onLog, {
      portraitLayout,
      activeRegion,
      slotId: opts.slotId,
      closeOverlay: closeTopRightOverlay,
    });
    result.files.push(...buyResult.files);

    onLog('Info 捲動擷取');
    const infoFiles = await captureInfoScroll(page, cfg, outDir, templatesDir, onLog, {
      portraitLayout,
      hadBuyPopup: buyResult.opened,
      activeRegion,
    });
    result.files.push(...infoFiles);

    onLog('回大廳');
    await returnToLobby(page, cfg, templatesDir, onLog, { portraitLayout, activeRegion });
    onLog(`完成：${outDir}`);
  } catch (err) {
    result.errors.push(String(err.message || err));
    result.ok = false;
    onLog(`錯誤：${err.message}`);
    if (!continueOnError) throw err;
    onLog('⚠ 本款擷取失敗，將繼續下一款（continueOnSlotError）');
  } finally {
    await browser.close();
  }

  return result;
}

export async function saveAuthInteractive() {
  const cfg = await loadConfig();
  const authPath = path.join(TOOL_ROOT, cfg.authFile);
  await ensureDir(path.dirname(authPath));

  const browser = await chromium.launch({
    headless: false,
    args: windowArgs(cfg),
  });
  const context = await browser.newContext({ viewport: cfg.viewport });
  const page = await context.newPage();
  await forceWindowBounds(page, cfg);

  console.log('請在瀏覽器手動登入大廳，完成後回到終端機按 Enter…');
  await page.goto(cfg.lobbyUrl);
  await new Promise(resolve => {
    process.stdin.once('data', () => resolve());
  });

  await context.storageState({ path: authPath });
  console.log(`已儲存登入狀態：${authPath}`);
  await browser.close();
}
