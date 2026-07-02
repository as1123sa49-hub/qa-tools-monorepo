import path from 'node:path';
import { findTemplate, loadTemplate } from './template-match.js';
import { saveDebug } from './capture-debug.js';
import { clickCanvasByTemplate, smartClick } from './template-click.js';
import { mergePortraitFractions } from './portrait-layout.js';
import {
  waitForUnityCanvas,
  diffRatio,
  clickCanvas,
  clickCanvasFraction,
  screenshotBuffer,
  screenshot,
} from './browser-utils.js';

/** 直版遊戲條內點擊驗證（排除 letterbox 假陽性） */
function isInPortraitStrip(pageX, pageY, activeRegion, padding = 24, viewportHeight = 911) {
  if (!activeRegion?.width) return true;
  const { left, width } = activeRegion;
  const stripRight = left + width;
  return (
    pageX >= left - padding &&
    pageX <= stripRight + padding &&
    pageY >= padding &&
    pageY <= viewportHeight - padding
  );
}

/** 合併直版 infoScroll 覆寫參數 */
function resolveInfoScrollConfig(cfg, portraitLayout, activeRegion) {
  const base = { ...cfg.infoScroll };
  if (portraitLayout && cfg.infoScroll?.portrait) {
    const p = cfg.infoScroll.portrait;
    if (p.dragStartFraction) base.dragStartFraction = p.dragStartFraction;
    if (p.dragDistance != null) base.dragDistance = p.dragDistance;
    if (p.saveMovedThreshold != null) base.saveMovedThreshold = p.saveMovedThreshold;
    if (p.textRegion) base.textRegion = p.textRegion;
    if (p.openWaitMs != null) base.openWaitMs = p.openWaitMs;
    if (p.openThreshold != null) base.openThreshold = p.openThreshold;
    if (p.bottomThreshold != null) base.bottomThreshold = p.bottomThreshold;
    if (activeRegion?.width) {
      base.textRegion = {
        left: activeRegion.left,
        top: activeRegion.top,
        width: activeRegion.width,
        height: Math.min(activeRegion.height + 180, (cfg.viewport?.height ?? 911) - activeRegion.top),
      };
    }
  }
  return base;
}

/** 直版單次點擊（模板或 canvas 比例） */
async function clickPortraitStrategy(page, cfg, templatesDir, strategy, onLog, { activeRegion } = {}) {
  await waitForUnityCanvas(page);
  if (strategy.kind === 'template') {
    const validate = strategy.activeRegion
      ? (x, y) => isInPortraitStrip(x, y, strategy.activeRegion, 24, cfg.viewport?.height)
      : null;
    const result = await clickCanvasByTemplate(page, cfg, templatesDir, strategy.key, onLog, {
      allowCoordFallback: false,
      searchRegion: strategy.region,
      skipDebug: true,
      validatePagePoint: validate,
    });
    if (result.method !== 'template') return false;
    return true;
  }
  if (strategy.kind === 'fraction') {
    await clickCanvasFraction(page, strategy.fx, strategy.fy, {
      delay: 100,
      double: Boolean(strategy.double),
    });
    const dbl = strategy.double ? ' 雙擊' : '';
    const fx = Number(strategy.fx).toFixed(4);
    const fy = Number(strategy.fy).toFixed(4);
    onLog?.(`  [${strategy.key || 'ui'}] canvas 比例點擊 (${fx}, ${fy})${strategy.note ? ` ${strategy.note}` : ''}${dbl}`);
    return true;
  }
  return false;
}

function infoClickNetworkEnabled(scrollCfg) {
  return scrollCfg.infoClickNetwork?.enabled !== false;
}

async function isInfoClickNetworkResponse(res, pattern) {
  if (!res.url().includes(pattern)) return false;
  if (res.request().method() !== 'POST') return false;
  try {
    const body = await res.json();
    return body?.success === true;
  } catch {
    return res.status() >= 200 && res.status() < 300;
  }
}

async function clickAndWaitInfoNetwork(page, scrollCfg, clickFn, onLog) {
  const netCfg = scrollCfg.infoClickNetwork ?? {};
  if (!infoClickNetworkEnabled(scrollCfg)) {
    await clickFn();
    return { used: false, ok: null };
  }

  const pattern = netCfg.urlPattern ?? 'api.analysiscloud.info/api/loginAction/user/click';
  const timeout = netCfg.timeoutMs ?? 5000;

  const responsePromise = page
    .waitForResponse(res => isInfoClickNetworkResponse(res, pattern), { timeout })
    .catch(() => null);

  await clickFn();
  const res = await responsePromise;

  if (res) {
    onLog?.('  [info_icon] network click API 回應 success');
    return { used: true, ok: true };
  }
  onLog?.(`  [info_icon] network 未收到 click API（${timeout}ms）`);
  return { used: true, ok: false };
}

async function isInfoPanelOpen(page, cfg, templatesDir, portraitLayout) {
  const tplName = cfg.templates?.info_close_x;
  if (!tplName) return false;
  const tplBuf = await loadTemplate(templatesDir, tplName);
  if (!tplBuf) return false;
  const region = portraitLayout
    ? (cfg.searchRegions?.info_close_portrait ?? cfg.searchRegions?.top_right)
    : cfg.searchRegions?.top_right;
  if (!region) return false;
  const shot = await page.screenshot({ type: 'png' });
  const threshold = cfg.templateThresholds?.info_close_x ?? 0.55;
  const hit = await findTemplate(shot, tplBuf, region, threshold);
  return hit.matched;
}

/** 關閉右上角彈窗（Buy / Info） */
export async function closeTopRightOverlay(page, cfg, templatesDir, onLog, {
  portraitLayout,
  key = 'info_close_x',
  activeRegion,
} = {}) {
  if (portraitLayout) {
    const frac = mergePortraitFractions(cfg, activeRegion)[key] ?? { fx: 0.88, fy: 0.08 };
    await clickCanvasFraction(page, frac.fx, frac.fy, { delay: 80 });
    onLog?.(`  [${key}] canvas 比例點擊 (${frac.fx.toFixed(4)}, ${frac.fy.toFixed(4)})`);
    return;
  }
  if (cfg.canvasClicks?.[key]) {
    await clickCanvas(page, cfg, key);
    onLog?.(`  [${key}] canvas 座標點擊 (${cfg.canvasClicks[key].x}, ${cfg.canvasClicks[key].y})`);
    return;
  }
  if (cfg.templates?.[key]) {
    await clickCanvasByTemplate(page, cfg, templatesDir, key, onLog, { skipDebug: true });
  }
}

async function prepareForInfoCapture(page, cfg, templatesDir, onLog, {
  portraitLayout,
  hadBuyPopup = false,
  activeRegion,
} = {}) {
  if (!portraitLayout || !hadBuyPopup) {
    if (portraitLayout) onLog?.('  無 Buy 彈窗殘留，跳過預清理');
    return;
  }
  await closeTopRightOverlay(page, cfg, templatesDir, onLog, {
    portraitLayout,
    key: 'info_close_x',
    activeRegion,
  });
  await page.waitForTimeout(1000);
  onLog?.('  已關閉 Buy 彈窗殘留，準備開 Info');
}

function portraitInfoStrategies(cfg, activeRegion) {
  const frac = mergePortraitFractions(cfg, activeRegion);
  const base = frac.info_icon;
  const alt = frac.info_icon_alt;
  return [
    { kind: 'fraction', key: 'info_icon', fx: base?.fx ?? 0.613, fy: base?.fy ?? 0.884, note: '實測右下 i' },
    { kind: 'fraction', key: 'info_icon', fx: base?.fx ?? 0.613, fy: base?.fy ?? 0.884, note: '實測右下 i 雙擊', double: true },
    { kind: 'template', key: 'info_icon', region: cfg.searchRegions?.info_icon_portrait, activeRegion },
    { kind: 'fraction', key: 'info_icon', fx: alt?.fx ?? 0.608, fy: alt?.fy ?? 0.878, note: '實測備援' },
  ];
}

async function clickUiElement(page, cfg, templatesDir, key, regionName, onLog, {
  portraitLayout = false,
  activeRegion,
} = {}) {
  await saveDebug(page, cfg, `before_${key}`, onLog);
  await waitForUnityCanvas(page);

  if (portraitLayout) {
    const frac = mergePortraitFractions(cfg, activeRegion)[key];
    if (frac && Number.isFinite(frac.fx) && Number.isFinite(frac.fy)) {
      await clickCanvasFraction(page, frac.fx, frac.fy, { delay: 80 });
      onLog?.(`  [${key}] canvas 比例點擊 (${frac.fx.toFixed(4)}, ${frac.fy.toFixed(4)})`);
      return { method: 'fraction' };
    }
    if (cfg.templates?.[key]) {
      const portraitRegion = cfg.searchRegions?.[`${key}_portrait`] || cfg.searchRegions?.[regionName];
      const result = await clickCanvasByTemplate(page, cfg, templatesDir, key, onLog, {
        allowCoordFallback: false,
        searchRegion: portraitRegion,
      });
      if (result.method === 'template') return result;
      onLog?.(`  [${key}] 直版模板未命中`);
    }
  }

  if (cfg.canvasClicks?.[key]) {
    await clickCanvas(page, cfg, key);
    onLog?.(`  [${key}] canvas 座標點擊 (${cfg.canvasClicks[key].x}, ${cfg.canvasClicks[key].y})`);
    return { method: 'coords' };
  }
  const r = await smartClick(page, cfg, templatesDir, key, regionName);
  onLog?.(`  [${key}] ${r.method} 點擊`);
  return r;
}

async function openInfoPanel(page, cfg, templatesDir, onLog, {
  portraitLayout = false,
  hadBuyPopup = false,
  activeRegion,
} = {}) {
  const scrollCfg = resolveInfoScrollConfig(cfg, portraitLayout, activeRegion);
  const openThreshold = scrollCfg.openThreshold ?? 0.12;
  const openWaitMs = scrollCfg.openWaitMs ?? 2000;
  const verifyRegion = portraitLayout ? scrollCfg.openVerifyRegion : null;
  const useNetwork = infoClickNetworkEnabled(scrollCfg);

  await prepareForInfoCapture(page, cfg, templatesDir, onLog, { portraitLayout, hadBuyPopup, activeRegion });
  await saveDebug(page, cfg, 'before_info_icon', onLog);
  const before = await screenshotBuffer(page);

  const strategies = portraitLayout
    ? portraitInfoStrategies(cfg, activeRegion)
    : [{ kind: 'landscape', key: 'info_icon' }];

  let lastRatio = 0;
  let lastCenterRatio = 0;
  let lastNetworkOk = false;

  for (let i = 0; i < strategies.length; i++) {
    const s = strategies[i];

    if (s.kind === 'template') {
      const tplBuf = await loadTemplate(templatesDir, cfg.templates?.info_icon);
      const region = s.region;
      if (tplBuf && region) {
        const shot = await page.screenshot({ type: 'png' });
        const threshold = cfg.templateThresholds?.info_icon ?? 0.6;
        const hit = await findTemplate(shot, tplBuf, region, threshold);
        if (!hit.matched) {
          onLog?.(`  [info_icon] 模板未命中（${hit.score.toFixed(3)}），換下一策略 (${i + 1}/${strategies.length})`);
          continue;
        }
        const pageX = hit.x + hit.width / 2;
        const pageY = hit.y + hit.height / 2;
        if (!isInPortraitStrip(pageX, pageY, activeRegion, 24, cfg.viewport?.height)) {
          onLog?.(`  [info_icon] 模板命中 (${Math.round(pageX)}, ${Math.round(pageY)}) 在遊戲條外，換下一策略 (${i + 1}/${strategies.length})`);
          continue;
        }
      }
    }

    const clickFn = async () => {
      if (s.kind === 'landscape') {
        await clickUiElement(page, cfg, templatesDir, 'info_icon', 'bottom_left', onLog, { portraitLayout: false });
        return;
      }
      await clickPortraitStrategy(page, cfg, templatesDir, s, onLog, { activeRegion });
    };

    const { used: networkUsed, ok: networkOk } = await clickAndWaitInfoNetwork(page, scrollCfg, clickFn, onLog);

    await page.waitForTimeout(networkOk ? 800 : openWaitMs);
    const after = await screenshotBuffer(page);
    lastRatio = await diffRatio(before, after);
    lastCenterRatio = verifyRegion ? await diffRatio(before, after, verifyRegion) : lastRatio;
    const closeVisible = await isInfoPanelOpen(page, cfg, templatesDir, portraitLayout);
    lastNetworkOk = networkOk === true;

    const visualNote = `全畫面 ${(lastRatio * 100).toFixed(1)}%、中央區 ${(lastCenterRatio * 100).toFixed(1)}%` +
      ` 關閉鈕 ${closeVisible ? '可見' : '不可見'}`;
    if (networkUsed) {
      onLog?.(`  Info 驗證：network ${networkOk ? 'success' : '未收到'}；${visualNote}`);
    } else {
      onLog?.(
        `  Info 驗證：${visualNote}` +
        `（需 ≥ ${(openThreshold * 100).toFixed(0)}%）`,
      );
    }

    const passed = networkOk === true
      || closeVisible
      || (!useNetwork && (portraitLayout ? lastCenterRatio >= openThreshold : lastRatio >= openThreshold));

    if (passed) {
      await saveDebug(page, cfg, 'info_opened', onLog);
      const via = networkOk ? 'network click' : closeVisible ? '關閉鈕' : '畫面變化';
      onLog?.(`  Info 已開啟（${via}）`);
      return Math.max(lastRatio, lastCenterRatio);
    }
    onLog?.(`  驗證未通過，換下一策略 (${i + 1}/${strategies.length})`);
  }

  await saveDebug(page, cfg, 'info_opened', onLog);
  const netNote = useNetwork ? `network ${lastNetworkOk ? 'ok' : '未收到'}、` : '';
  throw new Error(
    `Info 未開啟（${netNote}全畫面 ${(lastRatio * 100).toFixed(1)}%、中央 ${(lastCenterRatio * 100).toFixed(1)}%）`,
  );
}

export async function captureInfoScroll(page, cfg, outDir, templatesDir, onLog, {
  portraitLayout = false,
  hadBuyPopup = false,
  activeRegion,
} = {}) {
  await openInfoPanel(page, cfg, templatesDir, onLog, { portraitLayout, hadBuyPopup, activeRegion });

  const scrollCfg = resolveInfoScrollConfig(cfg, portraitLayout, activeRegion);
  const {
    mode = 'drag',
    wheelDelta = 240,
    dragStart = { x: 900, y: 620 },
    dragStartFraction,
    dragDistance = 300,
    dragSteps = 18,
    maxSteps = 40,
    settleMs = 550,
    saveMovedThreshold = 0.05,
    bottomThreshold = 0.03,
    staleLimit = 3,
    textRegion,
  } = scrollCfg;
  const scrollShots = [];

  await waitForUnityCanvas(page);
  const canvas = page.locator('#unity-canvas');

  const scrollOnce = async () => {
    const box = await canvas.boundingBox();
    if (mode === 'wheel') {
      await canvas.hover();
      await page.mouse.wheel(0, wheelDelta);
      return;
    }
    const ox = box?.x ?? 0;
    const oy = box?.y ?? 0;
    let x, yStart;
    if (dragStartFraction && box) {
      x = ox + box.width * dragStartFraction.fx;
      yStart = oy + box.height * dragStartFraction.fy;
    } else {
      x = ox + dragStart.x;
      yStart = oy + dragStart.y;
    }
    const yEnd = yStart - dragDistance;
    await page.mouse.move(x, yStart);
    await page.mouse.down();
    await page.mouse.move(x, yEnd, { steps: dragSteps });
    await page.waitForTimeout(120);
    await page.mouse.up();
  };

  const saveShot = async idx => {
    const p = path.join(outDir, `info_scroll_${String(idx).padStart(2, '0')}.png`);
    await screenshot(page, p);
    scrollShots.push(p);
    return p;
  };

  let idx = 1;
  await saveShot(idx);
  let prevBuf = await screenshotBuffer(page);
  let stale = 0;
  let reachedBottom = false;

  for (let s = 1; s <= maxSteps; s++) {
    await scrollOnce();
    await page.waitForTimeout(settleMs);

    const cur = await screenshotBuffer(page);
    const moved = await diffRatio(prevBuf, cur, textRegion);
    prevBuf = cur;

    if (moved < bottomThreshold) {
      stale++;
      if (stale >= staleLimit) {
        reachedBottom = true;
        onLog?.(`  已捲到底（連 ${staleLimit} 次幾乎無變化），共 ${idx} 張`);
        break;
      }
      continue;
    }

    stale = 0;
    if (moved >= saveMovedThreshold) {
      idx++;
      await saveShot(idx);
      onLog?.(`  捲動 ${(moved * 100).toFixed(0)}% → 存 info_scroll_${String(idx).padStart(2, '0')}`);
    }
  }
  if (!reachedBottom) onLog?.(`  ⚠ 達最大步數 ${maxSteps}，可能未捲到底，共 ${idx} 張`);

  await clickUiElement(page, cfg, templatesDir, 'info_close_x', 'top_right', onLog, { portraitLayout, activeRegion });
  await page.waitForTimeout(800);
  await saveDebug(page, cfg, 'after_close_info', onLog);
  return scrollShots;
}

export async function returnToLobby(page, cfg, templatesDir, onLog, {
  portraitLayout = false,
  activeRegion,
} = {}) {
  await clickUiElement(page, cfg, templatesDir, 'menu_hamburger', 'bottom_left', onLog, { portraitLayout, activeRegion });
  await page.waitForTimeout(800);
  await clickUiElement(page, cfg, templatesDir, 'menu_home', 'bottom_left', onLog, { portraitLayout, activeRegion });
  await page.waitForTimeout(2000);
}
