import fs from 'node:fs/promises';
import path from 'node:path';
import sharp from 'sharp';

/**
 * 在 region 內以 SSD 搜尋小模板（純 JS，無 OpenCV）
 * @returns {Promise<{ x: number, y: number, score: number } | null>}
 */
export async function findTemplate(screenBuffer, templateBuffer, region, threshold = 0.72) {
  const tplMeta = await sharp(templateBuffer).metadata();
  let tw = tplMeta.width;
  let th = tplMeta.height;
  if (!tw || !th) {
    return { x: 0, y: 0, score: -1, width: 0, height: 0, matched: false };
  }

  const screen = await sharp(screenBuffer)
    .extract(region)
    .ensureAlpha()
    .raw()
    .toBuffer({ resolveWithObject: true });

  const sw = screen.info.width;
  const sh = screen.info.height;

  // 模板大於搜尋區時等比縮小，否則迴圈不執行（分數維持 -1）
  const maxW = Math.max(8, Math.floor(sw * 0.92));
  const maxH = Math.max(8, Math.floor(sh * 0.92));
  if (tw > maxW || th > maxH) {
    const scale = Math.min(maxW / tw, maxH / th);
    tw = Math.max(8, Math.floor(tw * scale));
    th = Math.max(8, Math.floor(th * scale));
  }

  const tpl = await sharp(templateBuffer)
    .resize(tw, th, { fit: 'fill' })
    .ensureAlpha()
    .raw()
    .toBuffer({ resolveWithObject: true });

  const channels = screen.info.channels;
  const tplPx = tpl.data;
  const scrPx = screen.data;

  let best = { x: 0, y: 0, score: -1 };

  if (tw > sw || th > sh) {
    return { x: 0, y: 0, score: -1, width: tw, height: th, matched: false };
  }

  for (let y = 0; y <= sh - th; y += 2) {
    for (let x = 0; x <= sw - tw; x += 2) {
      let diff = 0;
      let count = 0;
      for (let ty = 0; ty < th; ty++) {
        for (let tx = 0; tx < tw; tx++) {
          const si = ((y + ty) * sw + (x + tx)) * channels;
          const ti = (ty * tw + tx) * channels;
          for (let c = 0; c < 3; c++) {
            const d = scrPx[si + c] - tplPx[ti + c];
            diff += d * d;
          }
          count += 3;
        }
      }
      const mse = diff / count;
      const score = 1 - Math.min(1, mse / (255 * 255));
      if (score > best.score) best = { x: region.left + x, y: region.top + y, score };
    }
  }

  const matched = best.score >= threshold;
  return {
    x: best.x,
    y: best.y,
    score: best.score,
    width: tw,
    height: th,
    matched,
  };
}

export async function loadTemplate(templatesDir, filename) {
  const p = path.join(templatesDir, filename);
  try {
    return await fs.readFile(p);
  } catch {
    return null;
  }
}
