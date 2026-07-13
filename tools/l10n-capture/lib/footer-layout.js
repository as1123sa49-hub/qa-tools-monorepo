/**
 * 主遊戲底部（footer）直橫版探測 — 不依賴 Balance/Bet/Win 等語系字。
 * 主訊號：底部有內容區的水平 span（letterbox 直版為中央窄條）。
 * 可選：金額座標中心（語系無關數字格式）作為輔助。
 */
import sharp from 'sharp';

export const LAYOUT_PORTRAIT = 'portrait';
export const LAYOUT_LANDSCAPE = 'landscape';

/** 金額／下注數字（不需語系標籤） */
export const AMOUNT_TEXT_RE = /(?:\bP\s*)?\d{1,3}(?:,\d{3})+(?:\.\d{2})?|\b\d+\.\d{2}\b/i;

/**
 * 由底部內容區的正規化 x 中心推導 layout（對齊 force-auto-play footer span 概念）。
 * @param {number[]} centersXNorm 0~1
 * @param {object} [cfg]
 * @returns {{ layout: 'portrait'|'landscape'|null, span: number, mid: number, n: number }}
 */
export function layoutFromContentCenters(centersXNorm, cfg = {}) {
  const fl = cfg.footerLayout || {};
  const portraitMaxSpan = fl.portraitMaxSpan ?? 0.35;
  const landscapeMinSpan = fl.landscapeMinSpan ?? 0.62;
  const centerMin = fl.portraitCenterMin ?? 0.22;
  const centerMax = fl.portraitCenterMax ?? 0.78;

  const xs = (centersXNorm || []).filter(x => Number.isFinite(x));
  if (xs.length < 2) {
    return { layout: null, span: 0, mid: 0.5, n: xs.length };
  }
  const lo = Math.min(...xs);
  const hi = Math.max(...xs);
  const span = hi - lo;
  const mid = (lo + hi) / 2;

  if (span <= portraitMaxSpan && mid >= centerMin && mid <= centerMax) {
    return { layout: LAYOUT_PORTRAIT, span, mid, n: xs.length };
  }
  if (span >= landscapeMinSpan) {
    return { layout: LAYOUT_LANDSCAPE, span, mid, n: xs.length };
  }
  return { layout: null, span, mid, n: xs.length };
}

/**
 * 從 OCR／字串命中的金額推導 layout（語系無關；標籤字僅加分不強制）。
 * @param {{ xNorm: number, text?: string }[]} hits
 */
export function layoutFromAmountHits(hits, cfg = {}) {
  const centers = [];
  for (const h of hits || []) {
    if (!Number.isFinite(h?.xNorm)) continue;
    if (h.text != null && h.text !== '' && !AMOUNT_TEXT_RE.test(String(h.text))) continue;
    centers.push(h.xNorm);
  }
  return { ...layoutFromContentCenters(centers, cfg), source: 'amount' };
}

/**
 * 截圖底部橫帶：找「非 letterbox 暗區」的欄位，用水平 span 判直／橫。
 * @param {Buffer} pngBuffer
 * @param {object} cfg
 */
export async function layoutFromBottomPixelStrip(pngBuffer, cfg = {}) {
  const vpW = cfg.viewport?.width ?? 1920;
  const vpH = cfg.viewport?.height ?? 911;
  const fl = cfg.footerLayout || {};
  const yStart = fl.yStart ?? 0.62;
  const cols = fl.probeCols ?? 96;
  const rows = fl.probeRows ?? 12;
  const contentMinBrightness = fl.contentMinBrightness ?? 40;

  const top = Math.max(0, Math.min(vpH - 20, Math.round(vpH * yStart)));
  const height = Math.max(20, vpH - top);

  let data;
  let info;
  try {
    const out = await sharp(pngBuffer)
      .extract({ left: 0, top, width: vpW, height })
      .resize(cols, rows, { fit: 'fill' })
      .removeAlpha()
      .raw()
      .toBuffer({ resolveWithObject: true });
    data = out.data;
    info = out.info;
  } catch {
    return { layout: null, span: 0, mid: 0.5, n: 0, source: 'pixel' };
  }

  const ch = info.channels;
  const contentXs = [];
  for (let x = 0; x < cols; x++) {
    let sum = 0;
    let n = 0;
    for (let y = 0; y < rows; y++) {
      const i = (y * cols + x) * ch;
      sum += (data[i] + data[i + 1] + data[i + 2]) / 3;
      n++;
    }
    const mean = sum / Math.max(1, n);
    if (mean >= contentMinBrightness) {
      contentXs.push(cols === 1 ? 0.5 : x / (cols - 1));
    }
  }

  return { ...layoutFromContentCenters(contentXs, cfg), source: 'pixel' };
}

/**
 * 合併 Loading 輪播判斷與 footer 探測。
 *
 * - footer 直版：可覆寫 carousel 橫版（黑邊／亮邊 letterbox 糾正）
 * - footer 橫版覆寫 carousel 直版：僅在 span 像「真實橫版底欄」時允許；
 *   span 接近滿寬（亮風景背景）則忽略，避免 Golden Bass 這類誤判
 *
 * @param {{
 *   carouselPortrait?: boolean|null,
 *   footerLayout?: string|null,
 *   footerSpan?: number|null,
 *   cfg?: object,
 * }} signals
 */
export function fuseLayoutSignals({
  carouselPortrait,
  footerLayout,
  footerSpan,
  cfg,
} = {}) {
  const fl = cfg?.footerLayout || {};
  const fullBleedMinSpan = fl.fullBleedMinSpan ?? 0.92;

  if (footerLayout === LAYOUT_PORTRAIT) {
    if (carouselPortrait === false) {
      return {
        portraitLayout: true,
        reason: 'footer-portrait-overrides-carousel',
      };
    }
    return { portraitLayout: true, reason: 'footer-portrait' };
  }

  if (footerLayout === LAYOUT_LANDSCAPE) {
    if (carouselPortrait === true) {
      const span = Number(footerSpan);
      // 底部幾乎整條都「有內容」→ 多半是亮邊 letterbox，不可覆寫直版
      if (Number.isFinite(span) && span >= fullBleedMinSpan) {
        return {
          portraitLayout: true,
          reason: 'carousel-portrait-keeps-footer-full-bleed-ignored',
        };
      }
      // span 未回傳時也不敢覆寫（避免舊呼叫誤傷）
      if (!Number.isFinite(span)) {
        return {
          portraitLayout: true,
          reason: 'carousel-portrait-keeps-footer-span-unknown',
        };
      }
      return {
        portraitLayout: false,
        reason: 'footer-landscape-overrides-carousel',
      };
    }
    return { portraitLayout: false, reason: 'footer-landscape' };
  }

  if (carouselPortrait === true) {
    return { portraitLayout: true, reason: 'carousel-portrait' };
  }
  if (carouselPortrait === false) {
    return { portraitLayout: false, reason: 'carousel-landscape' };
  }
  return { portraitLayout: false, reason: 'default-landscape' };
}

/**
 * Continue 進主遊戲後：截圖底部像素探測並與 Loading 判斷 fuse。
 * @returns {Promise<{ portraitLayout: boolean, reason: string, footer: object }>}
 */
export async function refinePortraitLayoutAfterContinue(page, cfg, carouselPortrait, {
  screenshotFn,
  settleMs,
} = {}) {
  const fl = cfg.footerLayout || {};
  if (fl.enabled === false) {
    return {
      portraitLayout: Boolean(carouselPortrait),
      reason: carouselPortrait ? 'carousel-portrait' : 'carousel-landscape',
      footer: { layout: null, skipped: true },
    };
  }

  const waitMs = settleMs ?? fl.settleMs ?? 800;
  if (waitMs > 0 && page?.waitForTimeout) {
    await page.waitForTimeout(waitMs);
  }

  const shotFn = screenshotFn || (async p => p.screenshot({ type: 'png' }));
  let png;
  try {
    png = await shotFn(page);
  } catch {
    return {
      portraitLayout: Boolean(carouselPortrait),
      reason: 'carousel-fallback-screenshot-failed',
      footer: { layout: null, error: 'screenshot-failed' },
    };
  }

  const footer = await layoutFromBottomPixelStrip(png, cfg);
  const fused = fuseLayoutSignals({
    carouselPortrait,
    footerLayout: footer.layout,
    footerSpan: footer.span,
    cfg,
  });
  return { ...fused, footer };
}
