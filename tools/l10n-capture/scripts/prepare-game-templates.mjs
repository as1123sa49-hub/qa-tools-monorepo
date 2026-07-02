import fs from 'node:fs/promises';
import path from 'node:path';
import sharp from 'sharp';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const OUT_DIR = path.resolve(__dirname, '../templates/game');

async function pathExists(p) {
  try {
    await fs.access(p);
    return true;
  } catch {
    return false;
  }
}

/**
 * 從完整繼續按鈕圖裁切無文字區域（左側金邊圓帽 + 頂部金邊）
 * @param {string} continueSrc
 */
async function buildContinueTemplates(continueSrc) {
  const meta = await sharp(continueSrc).metadata();
  const w = meta.width;
  const h = meta.height;
  if (!w || !h) throw new Error('無法讀取繼續按鈕圖尺寸');

  const capW = Math.max(8, Math.round(w * 0.22));
  const topH = Math.max(6, Math.round(h * 0.2));

  await sharp(continueSrc)
    .extract({ left: 0, top: 0, width: capW, height: h })
    .png()
    .toFile(path.join(OUT_DIR, 'continue_btn_cap.png'));

  await sharp(continueSrc)
    .extract({ left: 0, top: 0, width: w, height: topH })
    .png()
    .toFile(path.join(OUT_DIR, 'continue_btn_top.png'));

  console.log(`✓ continue_btn_cap.png (${capW}×${h})`);
  console.log(`✓ continue_btn_top.png (${w}×${topH})`);
}

/**
 * 從 Buy Bonus 按鈕裁切左側圖示區（避開各語系文字）
 * @param {string} buySrc
 */
async function buildBuyBonusTemplate(buySrc) {
  const meta = await sharp(buySrc).metadata();
  const w = meta.width;
  const h = meta.height;
  if (!w || !h) throw new Error('無法讀取 Buy Bonus 按鈕圖尺寸');

  const iconW = Math.max(12, Math.round(w * 0.22));
  const iconH = Math.max(12, Math.round(h * 0.35));
  await sharp(buySrc)
    .extract({ left: 0, top: h - iconH, width: iconW, height: iconH })
    .png()
    .toFile(path.join(OUT_DIR, 'buy_bonus_btn.png'));

  console.log(`✓ buy_bonus_btn.png (${iconW}×${iconH}，左下邊框區，避開文字）`);
}

async function main() {
  const [, , arrowSrc, continueSrc, buySrc] = process.argv;
  await fs.mkdir(OUT_DIR, { recursive: true });

  const arrow = arrowSrc?.trim();
  const cont = continueSrc?.trim();
  const buy = buySrc?.trim();

  if (arrow && await pathExists(path.resolve(arrow))) {
    const dest = path.join(OUT_DIR, 'loading_arrow_right.png');
    await fs.copyFile(path.resolve(arrow), dest);
    console.log(`✓ loading_arrow_right.png`);
  }

  if (cont && await pathExists(path.resolve(cont))) {
    await buildContinueTemplates(path.resolve(cont));
  }

  if (buy && await pathExists(path.resolve(buy))) {
    await buildBuyBonusTemplate(path.resolve(buy));
  }

  const anyDone = await Promise.all(
    [arrow, cont, buy].map(async s => {
      if (!s) return false;
      return pathExists(path.resolve(s));
    }),
  ).then(r => r.some(Boolean));

  if (!anyDone) {
    console.log(`用法:
  node scripts/prepare-game-templates.mjs <右箭頭.png> <繼續按鈕整顆.png> [BuyBonus按鈕整顆.png]

繼續按鈕會自動裁成無文字的 continue_btn_cap.png（比對用）。
Buy Bonus 按鈕（可選）會裁成 buy_bonus_btn.png（左側圖示區，無文字）。
`);
    process.exit(1);
  }
}

main().catch(err => {
  console.error(err);
  process.exit(1);
});
