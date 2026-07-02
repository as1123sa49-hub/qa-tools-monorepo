import fs from 'node:fs/promises';
import path from 'node:path';

export const CAPTURE_META_FILE = 'capture-meta.json';

export async function loadCaptureMetaFromDir(outDir) {
  try {
    const raw = await fs.readFile(path.join(outDir, CAPTURE_META_FILE), 'utf8');
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

export async function saveCaptureMeta(outDir, patch) {
  const existing = await loadCaptureMetaFromDir(outDir);
  const meta = {
    ...existing,
    ...patch,
    portraitLayout: Boolean(patch.portraitLayout ?? existing?.portraitLayout),
  };
  await fs.writeFile(path.join(outDir, CAPTURE_META_FILE), JSON.stringify(meta, null, 2));
}
