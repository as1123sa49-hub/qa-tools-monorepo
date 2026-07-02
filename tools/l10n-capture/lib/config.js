import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { userOutputRoot } from './user-context.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

/** l10n-capture 工具根目錄（含 config.default.json、templates/） */
export const TOOL_ROOT = path.resolve(__dirname, '..');

export function mergeConfig(defaults, user) {
  const out = { ...defaults, ...user };
  if (defaults.viewport || user.viewport) {
    out.viewport = { ...defaults.viewport, ...user.viewport };
  }
  if (defaults.window || user.window) {
    out.window = {
      ...defaults.window,
      ...user.window,
      position: { ...defaults.window?.position, ...user.window?.position },
      size: { ...defaults.window?.size, ...user.window?.size },
    };
  }
  for (const key of ['langMap', 'envMap', 'verify', 'infoScroll', 'buyBonus', 'continue', 'searchRegions', 'langCheck', 'uiCanvasFractions']) {
    if (defaults[key] || user[key]) {
      out[key] = { ...defaults[key], ...user[key] };
      if (key === 'buyBonus' && defaults.buyBonus?.slotOverrides && user.buyBonus?.slotOverrides) {
        out.buyBonus.slotOverrides = {
          ...defaults.buyBonus.slotOverrides,
          ...user.buyBonus.slotOverrides,
        };
      }
      if (key === 'continue' && defaults.continue?.slotOverrides && user.continue?.slotOverrides) {
        out.continue.slotOverrides = {
          ...defaults.continue.slotOverrides,
          ...user.continue.slotOverrides,
        };
      }
    }
  }
  return out;
}

export async function loadConfig() {
  const defaults = JSON.parse(
    await fs.readFile(path.join(TOOL_ROOT, 'config.default.json'), 'utf8'),
  );
  const userPath = path.join(TOOL_ROOT, 'config.json');
  try {
    const user = JSON.parse(await fs.readFile(userPath, 'utf8'));
    return mergeConfig(defaults, user);
  } catch {
    return defaults;
  }
}

export function outputDir(cfg, env, lang, slotId, userId) {
  return path.join(userOutputRoot(userId, cfg), env, lang, slotId);
}

/**
 * 視窗位置/大小固定在單一螢幕（viewport 由 CDP 另外固定，截圖/點擊不受影響）。
 * 想放到螢幕 2 時，把 config.window.position.x 設成螢幕 1 寬度（例如 1920）。
 */
export function windowArgs(cfg) {
  const pos = cfg.window?.position || { x: 0, y: 0 };
  const size = cfg.window?.size || { width: 1280, height: 800 };
  return [
    `--window-position=${pos.x},${pos.y}`,
    `--window-size=${size.width},${size.height}`,
  ];
}

/**
 * 啟動後用 CDP 強制視窗位置/大小（壓過「上次最大化」的狀態）。
 * viewport 仍由 context 固定，截圖維持 1920×911。
 */
export async function forceWindowBounds(page, cfg) {
  const pos = cfg.window?.position || { x: 0, y: 0 };
  const size = cfg.window?.size || { width: 1280, height: 800 };
  try {
    const session = await page.context().newCDPSession(page);
    const { windowId } = await session.send('Browser.getWindowForTarget');
    await session.send('Browser.setWindowBounds', {
      windowId,
      bounds: { windowState: 'normal' },
    });
    await session.send('Browser.setWindowBounds', {
      windowId,
      bounds: {
        left: pos.x,
        top: pos.y,
        width: size.width,
        height: size.height,
        windowState: 'normal',
      },
    });
  } catch {
    // 非 Chromium 或不支援時忽略
  }
}
