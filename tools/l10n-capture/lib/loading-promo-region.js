/** Loading OCR 促銷文字帶：直版置中 vs 橫版全螢幕 */

export const PORTRAIT_ACTIVE_REGION_MAX_WIDTH = 600;

/** 比例（相對 viewport）轉像素區域 */
export function fractionsToRegion(frac, viewport) {
  if (!frac || !viewport?.width || !viewport?.height) return null;
  const left = Math.round((frac.left ?? 0) * viewport.width);
  const top = Math.round((frac.top ?? 0) * viewport.height);
  const width = Math.round((frac.width ?? 0) * viewport.width);
  const height = Math.round((frac.height ?? 0) * viewport.height);
  if (width < 20 || height < 20) return null;
  return { left, top, width, height };
}

/** 輪播區是否為直版置中（窄 + 水平置中；右側窄輪播仍屬橫版） */
export function isPortraitActiveRegion(region, cfg) {
  if (!region?.width) return false;
  const maxW = cfg?.loading?.portraitActiveRegionMaxWidth ?? PORTRAIT_ACTIVE_REGION_MAX_WIDTH;
  if (region.width >= maxW) return false;
  const vpW = cfg?.viewport?.width ?? 1920;
  const centerX = region.left + region.width / 2;
  const maxOffsetRatio = cfg?.loading?.portraitCenterMaxOffsetRatio ?? 0.12;
  return Math.abs(centerX - vpW / 2) <= vpW * maxOffsetRatio;
}

/** 是否直版置中（輪播區窄且水平置中） */
export function inferPortraitLayout(captureMeta, cfg) {
  if (captureMeta?.portraitLayout != null) return Boolean(captureMeta.portraitLayout);
  const region = captureMeta?.loadingPromoRegion;
  if (region?.width) return isPortraitActiveRegion(region, cfg);
  return null;
}

export function loadingCropLayoutKey(portraitLayout) {
  if (portraitLayout === true) return 'portrait';
  return 'landscape';
}

function promoFractionsForLayout(cfg, portraitLayout) {
  const loading = cfg?.loading ?? {};
  if (portraitLayout === true) {
    return loading.promoTextFractionsPortrait ?? loading.promoTextFractions ?? null;
  }
  return loading.promoTextFractionsLandscape
    ?? loading.promoTextFractionsPortrait
    ?? loading.promoTextFractions
    ?? null;
}

/** 橫版：從自動偵測輪播區取底部文字帶 */
export function promoTextBandFromCarousel(region, cfg) {
  if (!region?.width || !region?.height) return null;
  if (region.width < PORTRAIT_ACTIVE_REGION_MAX_WIDTH) return null;
  const band = cfg?.loading?.carouselTextBand ?? { topRatio: 0.68, heightRatio: 0.24 };
  const topRatio = band.topRatio ?? 0.68;
  const heightRatio = band.heightRatio ?? 0.24;
  const top = region.top + Math.round(region.height * topRatio);
  const height = Math.max(50, Math.round(region.height * heightRatio));
  const vpH = cfg?.viewport?.height ?? 911;
  if (top + height > vpH) {
    return { left: region.left, top, width: region.width, height: Math.max(50, vpH - top) };
  }
  return { left: region.left, top, width: region.width, height };
}

/**
 * 決定 Loading OCR 裁切區。
 * 直版：中央窄文字帶（S011/S012）。
 * 橫版：全畫面底部寬文字帶（促銷句常橫跨全寬，非僅右側輪播區）。
 * @returns {{ region: object|null, portraitLayout: boolean|null, layoutKey: string }}
 */
export function resolveLoadingPromoRegion(captureMeta, cfg) {
  const loading = cfg.loading ?? {};
  const portraitLayout = inferPortraitLayout(captureMeta, cfg);
  const layoutKey = loadingCropLayoutKey(portraitLayout);
  const carousel = captureMeta?.loadingPromoRegion;

  if (portraitLayout === true) {
    const frac = promoFractionsForLayout(cfg, true);
    const fromFractions = fractionsToRegion(frac, cfg.viewport);
    if (fromFractions) {
      return { region: fromFractions, portraitLayout, layoutKey: 'portrait' };
    }
    const fallback = loading.compareRegionCenter ?? loading.compareRegion ?? null;
    return { region: fallback, portraitLayout, layoutKey: 'portrait' };
  }

  const frac = promoFractionsForLayout(cfg, false);
  const fromFractions = fractionsToRegion(frac, cfg.viewport);
  if (fromFractions) {
    return { region: fromFractions, portraitLayout, layoutKey: 'landscape' };
  }
  if (carousel?.width) {
    const fromCarousel = promoTextBandFromCarousel(carousel, cfg);
    if (fromCarousel) {
      return { region: fromCarousel, portraitLayout, layoutKey: 'landscape' };
    }
  }
  const fallback = loading.compareRegion ?? loading.compareRegionCenter ?? null;
  return { region: fallback, portraitLayout, layoutKey: 'landscape' };
}

/** 擷取完成時寫入 capture-meta 的 promoTextRegion */
export function promoTextRegionForCapture(cfg, portraitLayout, loadingPromoRegion) {
  const { region } = resolveLoadingPromoRegion(
    { portraitLayout, loadingPromoRegion },
    cfg,
  );
  return region;
}

export function formatPromoRegion(r) {
  if (!r?.width) return '';
  return `[${r.left},${r.top} ${r.width}x${r.height}]`;
}
