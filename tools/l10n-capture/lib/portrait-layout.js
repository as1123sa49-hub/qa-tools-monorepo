/** 依 Loading 偵測的直版置中區域，換算 canvas 比例座標（避免點到 letterbox） */
export function portraitFractionsFromRegion(region, viewport = { width: 1920, height: 911 }) {
  if (!region?.width || !region?.height) return null;
  const vw = viewport.width ?? 1920;
  const vh = viewport.height ?? 911;
  const { left, top, width, height } = region;
  const infoFx = (left + width * 0.90) / vw;
  const menuFx = (left + width * 0.10) / vw;
  const buyFx = (left + width * 0.12) / vw;
  const closeFx = (left + width * 0.90) / vw;
  const bottomFy = 0.93;
  const closeFy = 0.08;
  const buyFy = (top + height * 0.72) / vh;
  const homeFy = (top + height * 0.50) / vh;
  return {
    info_icon: { fx: infoFx, fy: bottomFy },
    info_icon_alt: { fx: (left + width * 0.93) / vw, fy: bottomFy - 0.02 },
    menu_hamburger: { fx: menuFx, fy: bottomFy },
    menu_home: { fx: menuFx, fy: homeFy },
    info_close_x: { fx: closeFx, fy: closeFy },
    buy_bonus_btn: { fx: buyFx, fy: buyFy },
  };
}

export function mergePortraitFractions(cfg, activeRegion) {
  const fromRegion = portraitFractionsFromRegion(activeRegion, cfg.viewport);
  const fromCfg = cfg.uiCanvasFractions?.portrait ?? {};
  return fromRegion ? { ...fromRegion, ...fromCfg } : fromCfg;
}

export function portraitBuyBonusStrategies(cfg, activeRegion) {
  const frac = mergePortraitFractions(cfg, activeRegion).buy_bonus_btn;
  return [
    { kind: 'fraction', key: 'buy_bonus_btn', fx: frac?.fx ?? 0.40, fy: frac?.fy ?? 0.763, note: '實測左側 Buy' },
  ];
}
