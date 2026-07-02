import fs from 'node:fs/promises';
import path from 'node:path';
import { TOOL_ROOT } from './config.js';
import { ensureDir } from './browser-utils.js';

export async function saveDebug(page, cfg, label, onLog) {
  if (!cfg.debug) return;
  try {
    const dir = path.join(cfg._outDir || TOOL_ROOT, '_debug');
    await ensureDir(dir);
    const p = path.join(dir, `${Date.now()}_${label}.png`);
    await page.screenshot({ path: p, type: 'png' });
    onLog?.(`  [debug] 已存 ${path.basename(p)}`);
  } catch { /* ignore */ }
}

export async function saveLangDebug(cfg, label, content, onLog) {
  if (!cfg.debug) return;
  try {
    const dir = path.join(cfg._outDir || TOOL_ROOT, '_debug');
    await ensureDir(dir);
    const p = path.join(dir, `lang_check_${label}.txt`);
    await fs.writeFile(p, content, 'utf8');
    onLog?.(`  [lang-debug] 已存 ${path.basename(p)}`);
  } catch { /* ignore */ }
}
