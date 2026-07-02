import { findTemplate, loadTemplate } from './template-match.js';
import {
  waitForUnityCanvas,
  clickCanvas,
  clickCanvasPoint,
  clickAt,
} from './browser-utils.js';
import { saveDebug } from './capture-debug.js';

/** 模板比對後點擊 #unity-canvas（忽略按鈕文字）；失敗可選擇 fallback canvasClicks */
export async function clickCanvasByTemplate(page, cfg, templatesDir, key, onLog, {
  allowCoordFallback = true,
  searchRegion = null,
  skipDebug = false,
  validatePagePoint = null,
} = {}) {
  const tplName = cfg.templates?.[key];
  const region = searchRegion || cfg.searchRegions?.[key];
  const threshold = cfg.templateThresholds?.[key] ?? cfg.templateThreshold ?? 0.68;

  await waitForUnityCanvas(page);
  if (!skipDebug) await saveDebug(page, cfg, `before_${key}`, onLog);

  let lastScore = 0;
  if (tplName && region) {
    const tplBuf = await loadTemplate(templatesDir, tplName);
    if (!tplBuf) {
      onLog?.(`  [${key}] 找不到模板檔 ${tplName}${allowCoordFallback ? '，改用座標' : ''}`);
    } else {
      const canvas = page.locator('#unity-canvas');
      const box = await canvas.boundingBox();
      if (!box) throw new Error('無法取得 #unity-canvas 位置');

      const shot = await page.screenshot({ type: 'png' });
      const hit = await findTemplate(shot, tplBuf, region, threshold);
      if (!hit) {
        onLog?.(`  [${key}] 模板比對失敗`);
      } else {
        lastScore = hit.score;
        onLog?.(`  [${key}] 模板最佳分數 ${hit.score.toFixed(3)}（門檻 ${threshold}）→ ${hit.matched ? '命中' : '未達門檻'}`);

        if (hit.matched) {
          const offset = cfg.templateClickOffsets?.[key] || { x: 0, y: 0 };
          const pageX = hit.x + hit.width / 2 + offset.x;
          const pageY = hit.y + hit.height / 2 + offset.y;
          const minPageY = cfg.continueMinPageY ?? 750;
          if (validatePagePoint && !validatePagePoint(pageX, pageY)) {
            onLog?.(`  [${key}] 命中點 (${Math.round(pageX)}, ${Math.round(pageY)}) 在遊戲條外，視為假陽性`);
          } else if (key === 'continue_btn' && pageY < minPageY) {
            onLog?.(`  [${key}] 命中點 y=${Math.round(pageY)} 過高（< ${minPageY}），視為假陽性`);
          } else {
            await clickCanvasPoint(page, pageX, pageY, { delay: 80 });
            onLog?.(`  [${key}] 模板點擊畫面座標 (${Math.round(pageX)}, ${Math.round(pageY)})`);
            return { method: 'template', score: hit.score, pageX, pageY };
          }
        }
      }
    }
  }

  if (!allowCoordFallback) {
    return { method: 'miss', score: lastScore };
  }

  const pos = cfg.canvasClicks?.[key];
  await clickCanvas(page, cfg, key);
  onLog?.(`  [${key}] 座標點擊 canvas(${pos?.x}, ${pos?.y})`);
  return { method: 'coords' };
}

/** 模板優先點擊，失敗用座標 */
export async function smartClick(page, cfg, templatesDir, key, regionName) {
  const tplName = cfg.templates[key];
  const fallback = cfg.clicks[key];
  const region = cfg.searchRegions[regionName] || { left: 0, top: 0, width: 1920, height: 911 };

  if (tplName) {
    const tplBuf = await loadTemplate(templatesDir, tplName);
    if (tplBuf) {
      const shot = await page.screenshot({ type: 'png' });
      const hit = await findTemplate(shot, tplBuf, region, cfg.templateThreshold);
      if (hit.matched) {
        await clickAt(page, hit.x + 8, hit.y + 8);
        return { method: 'template', ...hit };
      }
    }
  }

  if (!fallback) throw new Error(`無法點擊 ${key}：模板與座標皆未設定`);
  await clickAt(page, fallback.x, fallback.y);
  return { method: 'coords', ...fallback };
}

export async function resolveTemplateClickCandidate(page, cfg, templatesDir, key, region, onLog) {
  const tplName = cfg.templates?.[key];
  if (!tplName || !region?.width) return null;
  const tplBuf = await loadTemplate(templatesDir, tplName);
  if (!tplBuf) return null;
  const threshold = cfg.templateThresholds?.[key] ?? cfg.templateThreshold ?? 0.68;
  const shot = await page.screenshot({ type: 'png' });
  const hit = await findTemplate(shot, tplBuf, region, threshold);
  if (!hit?.matched) return null;
  const offset = cfg.templateClickOffsets?.[key] || { x: 0, y: 0 };
  const pageX = Math.round(hit.x + hit.width / 2 + offset.x);
  const pageY = Math.round(hit.y + hit.height / 2 + offset.y);
  onLog?.(`  [${key}] 模板候選 (${pageX}, ${pageY}) 分數 ${hit.score.toFixed(3)}`);
  return { pageX, pageY, note: '模板候選' };
}
