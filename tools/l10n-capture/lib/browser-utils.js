import fs from 'node:fs/promises';
import sharp from 'sharp';

export async function ensureDir(dir) {
  await fs.mkdir(dir, { recursive: true });
}

export async function waitForUnityCanvas(page, timeout = 60000) {
  await page.locator('#unity-canvas').waitFor({ state: 'visible', timeout });
}

/** 計算截圖平均亮度（0~255）。載入頁≈17、介紹頁≈108，可用門檻分辨 */
async function meanBrightness(buffer) {
  const { data, info } = await sharp(buffer)
    .resize(64, 36, { fit: 'fill' })
    .raw()
    .toBuffer({ resolveWithObject: true });
  let sum = 0;
  let n = 0;
  for (let i = 0; i < data.length; i += info.channels) {
    sum += (data[i] + data[i + 1] + data[i + 2]) / 3;
    n++;
  }
  return sum / n;
}

/** 等到畫面亮度超過門檻（載入完成、介紹頁出現） */
export async function waitForBright(page, { minBrightness = 60, timeout = 45000, interval = 700 } = {}) {
  const start = Date.now();
  let last = 0;
  while (Date.now() - start < timeout) {
    const buf = await page.screenshot({ type: 'png' });
    last = await meanBrightness(buf);
    if (last >= minBrightness) return last;
    await page.waitForTimeout(interval);
  }
  return last;
}

/** 回傳兩張截圖的差異比例（0~1）。可選 region 只比某區塊（避開動畫） */
export async function diffRatio(a, b, region) {
  const toSmall = buf => {
    let img = sharp(buf);
    if (region) img = img.extract(region);
    return img.resize(80, 45, { fit: 'fill' }).raw().toBuffer({ resolveWithObject: true });
  };
  const ra = await toSmall(a);
  const rb = await toSmall(b);
  if (ra.data.length !== rb.data.length) return 1;
  const ch = ra.info.channels;
  let diff = 0;
  let n = 0;
  for (let i = 0; i < ra.data.length; i += ch) {
    const d =
      Math.abs(ra.data[i] - rb.data[i]) +
      Math.abs(ra.data[i + 1] - rb.data[i + 1]) +
      Math.abs(ra.data[i + 2] - rb.data[i + 2]);
    if (d > 60) diff++;
    n++;
  }
  return diff / n;
}

/**
 * 以「畫面像素座標」點擊 canvas。
 * Playwright 的 position 是相對 canvas 元素左上角，會再自動加上 box.x/box.y，
 * 因此必須先減掉 box 偏移，否則置中/窄版（直版）canvas 會點錯位置。
 */
export async function clickCanvasPoint(page, pageX, pageY, { delay } = {}) {
  const canvas = page.locator('#unity-canvas');
  const box = await canvas.boundingBox();
  if (!box) throw new Error('無法取得 #unity-canvas 位置');
  const opts = { position: { x: pageX - box.x, y: pageY - box.y } };
  if (delay != null) opts.delay = delay;
  await canvas.click(opts);
}

/** 以 canvas 元素內比例座標點擊（直版遊戲按鈕在 canvas 內置中底部時最準） */
export async function clickCanvasFraction(page, fx, fy, { delay, double = false } = {}) {
  const canvas = page.locator('#unity-canvas');
  const box = await canvas.boundingBox();
  if (!box) throw new Error('無法取得 #unity-canvas 位置');
  const pos = { x: box.width * fx, y: box.height * fy };
  if (double) {
    await canvas.dblclick({ ...pos, delay: delay ?? 80 });
  } else {
    const opts = { position: pos };
    if (delay != null) opts.delay = delay;
    await canvas.click(opts);
  }
}

/** 以畫面絕對像素座標點擊（截圖量測的座標用這個較準，不受 canvas box 換算誤差影響） */
export async function clickPagePoint(page, pageX, pageY) {
  await page.mouse.click(pageX, pageY);
}

export async function screenshotBuffer(page) {
  return page.screenshot({ type: 'png' });
}

export async function screenshot(page, filePath) {
  await page.screenshot({ path: filePath, type: 'png' });
}

export async function clickAt(page, x, y) {
  await page.mouse.click(x, y);
}

/** Unity Canvas 固定座標點擊（模板失敗時 fallback） */
export async function clickCanvas(page, cfg, key) {
  const pos = cfg.canvasClicks?.[key];
  if (!pos) throw new Error(`未設定 canvas 點擊：${key}`);
  await waitForUnityCanvas(page);
  await clickCanvasPoint(page, pos.x, pos.y);
}
