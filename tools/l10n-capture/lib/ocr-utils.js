import fs from 'node:fs/promises';
import path from 'node:path';
import sharp from 'sharp';
import { buyCaptureFiles, infoCaptureFiles, isBuyKey, loadingCaptureFiles } from './text-match.js';

const CACHE_FILE = 'ocr-cache.json';
export const CACHE_VERSION = 2;

/** 快取 entry schema：
 *  - 'single'：該 entry 存的是「這張圖自己的」OCR 文字（info_scroll/buy/單張 Loading 分頁）
 *  - 'shared'：Loading 合併 OCR 分頁失敗時，多張共用的整批文字
 *  舊 v1 entry 無 schema 欄位：非 Loading 視為 single 可沿用；Loading 視為 shared 需重取一次以取得分頁。 */
export const OCR_SCHEMA_SINGLE = 'single';
export const OCR_SCHEMA_SHARED = 'shared';

/** 依工作表 key 決定需要 OCR 的檔案（略過用不到的圖） */
export function filesNeededForItems(items, allFiles) {
  const needed = new Set();
  let hasLoading = false;
  let hasInfoScroll = false;
  let hasBuy = false;

  for (const { key } of items) {
    if (/^Loading_\d+$/i.test(key)) hasLoading = true;
    else if (isBuyKey(key)) hasBuy = true;
    else hasInfoScroll = true;
  }

  if (hasLoading) loadingCaptureFiles(allFiles).forEach(f => needed.add(f));
  if (hasInfoScroll) infoCaptureFiles(allFiles).forEach(f => needed.add(f));
  if (hasBuy) buyCaptureFiles(allFiles).forEach(f => needed.add(f));

  return [...needed].sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
}

/** 縮圖 + JPEG，降低 Vision image token */
export async function prepareOcrBuffer(buffer, { maxWidth = 1280, jpegQuality = 85 } = {}) {
  let img = sharp(buffer);
  const meta = await img.metadata();
  if (meta.width && meta.width > maxWidth) {
    img = img.resize(maxWidth, null, { withoutEnlargement: true });
  }
  const out = await img.jpeg({ quality: jpegQuality }).toBuffer();
  return { buffer: out, mimeType: 'image/jpeg' };
}

/** Loading 輪播區裁切後再 OCR，避免讀到底部 Continue / 版本號 */
export async function prepareLoadingOcrBuffer(buffer, region, { maxWidth = 1280, jpegQuality = 85 } = {}) {
  if (!region?.width || !region?.height) {
    return prepareOcrBuffer(buffer, { maxWidth, jpegQuality });
  }
  const meta = await sharp(buffer).metadata();
  const imgW = meta.width ?? 1920;
  const imgH = meta.height ?? 911;
  const left = Math.max(0, Math.min(Math.round(region.left), imgW - 1));
  const top = Math.max(0, Math.min(Math.round(region.top), imgH - 1));
  const width = Math.min(Math.round(region.width), imgW - left);
  const height = Math.min(Math.round(region.height), imgH - top);
  if (width < 50 || height < 50) {
    return prepareOcrBuffer(buffer, { maxWidth, jpegQuality });
  }
  let img = sharp(buffer).extract({ left, top, width, height });
  const minCropHeight = 140;
  if (height < minCropHeight) {
    img = img.resize({ height: minCropHeight, fit: 'contain', background: { r: 0, g: 0, b: 0, alpha: 0 } });
  }
  const cropMeta = await img.metadata();
  const cropW = cropMeta.width ?? width;
  if (cropW > maxWidth) {
    img = img.resize(maxWidth, null, { withoutEnlargement: true });
  }
  const out = await img.jpeg({ quality: jpegQuality }).toBuffer();
  return { buffer: out, mimeType: 'image/jpeg' };
}

function cacheMetaKey({ provider, modelId, maxWidth }) {
  return `${provider}|${modelId}|w${maxWidth}`;
}

export async function loadOcrCache(imagesDir) {
  try {
    const raw = await fs.readFile(path.join(imagesDir, CACHE_FILE), 'utf8');
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

export async function saveOcrCache(imagesDir, cache) {
  await fs.writeFile(path.join(imagesDir, CACHE_FILE), JSON.stringify(cache, null, 2), 'utf8');
}

/**
 * 單筆 entry 是否可沿用（不含 mtime 檢查，mtime 由呼叫端比對）。
 * - 非 Loading：single 語意未變，舊 v1（無 schema）也可沿用。
 * - Loading：需 v2 以後的 schema（single/shared）；舊 v1（無 schema）強制重取一次以建立分頁。
 */
function hasOcrText(text) {
  return Boolean(text && String(text).replace(/\s+/g, '').length);
}

export function cropRegionKey(region) {
  if (!region?.width) return '';
  return `${region.left},${region.top},${region.width},${region.height}`;
}

export function isEntryReusable(entry, file, {
  expectLoadingCrop = false,
  expectLoadingCropLayout,
  expectLoadingCropRegion,
} = {}) {
  if (!entry || entry.text == null || !hasOcrText(entry.text)) return false;
  if (isLoadingFile(file)) {
    if (expectLoadingCrop && !entry.loadingCrop) return false;
    if (expectLoadingCrop && expectLoadingCropLayout) {
      if (!entry.loadingCropLayout || entry.loadingCropLayout !== expectLoadingCropLayout) return false;
    }
    if (expectLoadingCrop && expectLoadingCropRegion) {
      if (!entry.loadingCropRegion || entry.loadingCropRegion !== expectLoadingCropRegion) return false;
    }
    return entry.schema === OCR_SCHEMA_SINGLE || entry.schema === OCR_SCHEMA_SHARED;
  }
  return true;
}

/**
 * @returns {{ text: string, fromCache: boolean }}
 */
export async function resolveOcrText({
  imagesDir,
  file,
  cache,
  cacheEnabled,
  forceOcr,
  filePath,
  ocrFn,
  textOverride,
  expectLoadingCrop = false,
  expectLoadingCropLayout,
  expectLoadingCropRegion,
}) {
  const stat = await fs.stat(filePath);
  const mtimeMs = stat.mtimeMs;

  if (textOverride != null) {
    if (cacheEnabled && cache) {
      cache.entries[file] = { mtimeMs, text: textOverride, schema: OCR_SCHEMA_SINGLE };
    }
    return { text: textOverride, fromCache: false, deduped: true };
  }

  if (cacheEnabled && cache && !forceOcr) {
    const hit = cache.entries?.[file];
    if (hit && hit.mtimeMs === mtimeMs && isEntryReusable(hit, file, {
      expectLoadingCrop,
      expectLoadingCropLayout,
      expectLoadingCropRegion,
    })) {
      return { text: hit.text, fromCache: true };
    }
  }

  const raw = await fs.readFile(filePath);
  const text = await ocrFn(raw);

  if (cacheEnabled && cache && hasOcrText(text)) {
    cache.entries[file] = {
      mtimeMs,
      text,
      schema: OCR_SCHEMA_SINGLE,
      ...(expectLoadingCrop ? {
        loadingCrop: true,
        loadingCropLayout: expectLoadingCropLayout || 'unknown',
        loadingCropRegion: expectLoadingCropRegion || '',
      } : {}),
    };
  }
  return { text, fromCache: false };
}

export function textToLines(text) {
  return text.split(/\r?\n/).map(s => s.trim()).filter(Boolean);
}

export function isInfoScrollFile(file) {
  return /^info_scroll_/i.test(file);
}

export function isLoadingFile(file) {
  return /^loading_\d+\.png$/i.test(file);
}

export function createOcrCache({ provider, modelId, maxWidth }) {
  return {
    version: CACHE_VERSION,
    metaKey: cacheMetaKey({ provider, modelId, maxWidth }),
    provider,
    modelId,
    maxWidth,
    entries: {},
  };
}

export function isCacheCompatible(cache, { provider, modelId, maxWidth }) {
  if (!cache || cache.version !== CACHE_VERSION) return false;
  return cache.metaKey === cacheMetaKey({ provider, modelId, maxWidth });
}

/** 只比對 provider/model/maxWidth（metaKey）；相同即可逐筆沿用舊快取（跨 version） */
export function isCacheMetaMatch(cache, { provider, modelId, maxWidth }) {
  return Boolean(cache) && cache.metaKey === cacheMetaKey({ provider, modelId, maxWidth });
}

export { CACHE_FILE };
