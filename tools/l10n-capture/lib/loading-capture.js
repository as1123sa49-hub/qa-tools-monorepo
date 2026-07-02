import fs from 'node:fs/promises';
import path from 'node:path';
import sharp from 'sharp';
import { isPortraitActiveRegion } from './loading-promo-region.js';
import {
  ensureDir,
  waitForUnityCanvas,
  waitForBright,
  diffRatio,
  clickCanvas,
  screenshotBuffer,
} from './browser-utils.js';

/** 等促銷區相對參考圖出現變化（換到下一張輪播圖） */
async function waitForPromoChange(page, refBuf, region, changeThreshold, { timeout = 9000, poll = 500 } = {}) {
  const start = Date.now();
  let last = 0;
  while (Date.now() - start < timeout) {
    await page.waitForTimeout(poll);
    const cur = await screenshotBuffer(page);
    last = await diffRatio(refBuf, cur, region);
    if (last >= changeThreshold) return { changed: true, ratio: last };
  }
  return { changed: false, ratio: last };
}

/**
 * 自動偵測「有效變化區」：在自動輪播期間 diff 整個畫面，
 * 記錄每一格觀察窗內的最大差異，再用欄/列密度過濾掉背景零星動畫，
 * 回傳真正在變的促銷區塊像素範圍。
 */
export async function detectActiveRegion(page, refBuf, {
  timeout = 6000,
  poll = 500,
  cols = 64,
  rows = 36,
  cellDiffThreshold = 60,
  minChangedCells = 12,
  densityRatio = 0.25,
  minHeight = 350,
  maxTopRatio = 0.62,
} = {}) {
  const toGrid = async (buf) =>
    sharp(buf).resize(cols, rows, { fit: 'fill' }).raw().toBuffer({ resolveWithObject: true });

  const ref = await toGrid(refBuf);
  const ch = ref.info.channels;
  const maxDiff = new Uint16Array(cols * rows);

  const start = Date.now();
  let polls = 0;
  while (Date.now() - start < timeout) {
    await page.waitForTimeout(poll);
    let cur;
    try {
      cur = await toGrid(await screenshotBuffer(page));
    } catch {
      continue;
    }
    if (cur.data.length !== ref.data.length) continue;
    for (let idx = 0, p = 0; p < ref.data.length; p += ch, idx++) {
      const d =
        Math.abs(ref.data[p] - cur.data[p]) +
        Math.abs(ref.data[p + 1] - cur.data[p + 1]) +
        Math.abs(ref.data[p + 2] - cur.data[p + 2]);
      if (d > maxDiff[idx]) maxDiff[idx] = d;
    }
    polls++;
    if (polls >= 3) {
      let strong = 0;
      for (let i = 0; i < maxDiff.length; i++) if (maxDiff[i] > cellDiffThreshold) strong++;
      if (strong >= minChangedCells * 2) break;
    }
  }

  const colCount = new Array(cols).fill(0);
  const rowCount = new Array(rows).fill(0);
  let total = 0;
  for (let y = 0; y < rows; y++) {
    for (let x = 0; x < cols; x++) {
      if (maxDiff[y * cols + x] > cellDiffThreshold) {
        colCount[x]++;
        rowCount[y]++;
        total++;
      }
    }
  }
  if (total < minChangedCells) return null;

  const colThresh = Math.max(1, Math.max(...colCount) * densityRatio);
  const rowThresh = Math.max(1, Math.max(...rowCount) * densityRatio);

  let minX = -1, maxX = -1, minY = -1, maxY = -1;
  for (let x = 0; x < cols; x++) if (colCount[x] >= colThresh) { if (minX < 0) minX = x; maxX = x; }
  for (let y = 0; y < rows; y++) if (rowCount[y] >= rowThresh) { if (minY < 0) minY = y; maxY = y; }
  if (minX < 0 || minY < 0) return null;

  const vp = page.viewportSize() || { width: 1920, height: 911 };
  const cw = vp.width / cols;
  const chh = vp.height / rows;
  const padX = Math.round(vp.width * 0.02);
  const padY = Math.round(vp.height * 0.02);
  const left = Math.max(0, Math.floor(minX * cw) - padX);
  let top = Math.max(0, Math.floor(minY * chh) - padY);
  const right = Math.min(vp.width, Math.ceil((maxX + 1) * cw) + padX);
  const bottom = Math.min(vp.height, Math.ceil((maxY + 1) * chh) + padY);
  const width = right - left;
  let height = bottom - top;

  if (height < minHeight) {
    const centerY = top + height / 2;
    const newTop = Math.max(0, Math.floor(centerY - minHeight / 2));
    const newBottom = Math.min(vp.height, newTop + minHeight);
    top = newTop;
    height = newBottom - top;
  }

  if (top > vp.height * maxTopRatio) return null;
  if (width >= vp.width * 0.95 && height >= vp.height * 0.95) return null;
  return { left, top, width, height };
}

export async function captureLoading(page, cfg, outDir, templatesDir, onLog) {
  void templatesDir;
  await ensureDir(outDir);
  const {
    mode,
    initialWaitMs,
    slideWaitMs,
    maxSlides = 6,
    sameThreshold = 0.15,
    changeThreshold = 0.15,
    changeTimeoutMs = 9000,
    minSlidesBeforeCycle = 2,
    maxPromoWaitRounds = 12,
    compareRegion = { left: 1000, top: 60, width: 900, height: 420 },
    compareRegionCenter = { left: 640, top: 200, width: 640, height: 500 },
    autoRegion = true,
    autoRegionDetectMs = 6000,
    autoRegionMinHeight = 350,
    autoRegionMaxTopRatio = 0.62,
    introBrightness = 60,
  } = cfg.loading;

  await waitForUnityCanvas(page);
  const b = await waitForBright(page, { minBrightness: introBrightness, timeout: cfg.timeouts.gameLoadMs ?? 45000 });
  onLog?.(b >= introBrightness ? `  載入完成（亮度 ${b.toFixed(0)}）` : `  ⚠ 等待逾時，亮度僅 ${b.toFixed(0)}`);
  await page.waitForTimeout(initialWaitMs ?? 2000);

  const useAuto = (mode ?? 'auto') === 'auto';
  const files = [];
  const slides = [];

  let cur = await screenshotBuffer(page);
  let p = path.join(outDir, 'Loading_1.png');
  await fs.writeFile(p, cur);
  files.push(p);
  slides.push(cur);
  onLog?.('  已截 Loading_1');

  let region = compareRegion;
  let portraitLayout = false;
  if (autoRegion) {
    const detected = await detectActiveRegion(page, cur, {
      timeout: autoRegionDetectMs,
      minHeight: autoRegionMinHeight,
      maxTopRatio: autoRegionMaxTopRatio,
    });
    if (detected) {
      region = detected;
      portraitLayout = isPortraitActiveRegion(detected, cfg);
      const layoutNote = portraitLayout
        ? '（直版置中）'
        : (detected.width < (cfg.loading?.portraitActiveRegionMaxWidth ?? 600) ? '（橫版窄輪播）' : '');
      onLog?.(`  自動偵測輪播區 [${detected.left},${detected.top} ${detected.width}x${detected.height}]${layoutNote}`);
    } else {
      region = compareRegionCenter;
      portraitLayout = isPortraitActiveRegion(compareRegionCenter, cfg);
      onLog?.('  無輪播變化（靜態單張或偵測逾時），使用置中 compareRegion');
    }
  }

  let waitRounds = 0;
  while (files.length < maxSlides) {
    waitRounds++;
    if (waitRounds > maxPromoWaitRounds) {
      onLog?.(`  ⚠ 輪播等待超過 ${maxPromoWaitRounds} 輪，停止，共 ${files.length} 張`);
      break;
    }
    if (!useAuto) {
      await clickCanvas(page, cfg, 'loading_arrow_right');
      await page.waitForTimeout(slideWaitMs ?? 800);
    }
    const ref = slides[slides.length - 1];
    const { changed, ratio } = await waitForPromoChange(page, ref, region, changeThreshold, { timeout: changeTimeoutMs });
    if (!changed) {
      const msg = files.length === 1
        ? `  僅 1 張（無輪播或靜態介紹頁，變化 ${(ratio * 100).toFixed(0)}%）`
        : `  ⚠ 輪播未換頁（變化僅 ${(ratio * 100).toFixed(0)}%），停止，共 ${files.length} 張`;
      onLog?.(msg);
      break;
    }

    cur = await screenshotBuffer(page);
    if (files.length >= minSlidesBeforeCycle) {
      const dFirst = await diffRatio(slides[0], cur, region);
      const dPrev = await diffRatio(slides[slides.length - 1], cur, region);
      if (dFirst < sameThreshold && dPrev >= changeThreshold) {
        const n = files.length;
        const pagesNote = n < 3 ? `（${n} 頁輪播）` : '';
        onLog?.(
          `  循環回到 Loading_1（促銷區差異 < ${(sameThreshold * 100).toFixed(0)}%）${pagesNote}→ 已截完整循環，共 ${n} 張`,
        );
        break;
      }
    }

    const idx = files.length + 1;
    p = path.join(outDir, `Loading_${idx}.png`);
    await fs.writeFile(p, cur);
    files.push(p);
    slides.push(cur);
    onLog?.(`  已截 Loading_${idx}（與前頁差異 ${(ratio * 100).toFixed(0)}%）`);
  }

  return { files, portraitLayout, activeRegion: region };
}
