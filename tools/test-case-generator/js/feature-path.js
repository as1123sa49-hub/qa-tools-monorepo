/**
 * 功能頁面/元件路徑補全（心智圖子分類用）
 */
import { normalizeMainModule, stripFeatureMarkers, normalizeTierLevel } from './case-utils.js';

const FEATURE_PATH_DELIMITER_RE = /[/\-_]|(?:\s+[-–—]\s+)|(?:\s*[：:]\s+)/;

/** 規格章節名 → 心智圖 L2 慣用名 */
const L2_ALIASES = {
  '玩家資訊板': '玩家儀表板',
  '玩家信息板': '玩家儀表板',
  '資訊板': '玩家儀表板',
  '信息板': '玩家儀表板',
};

function applyL2Alias(name) {
  const s = (name || '').trim();
  return L2_ALIASES[s] || s;
}

function featureSimilar(a, b) {
  const x = stripFeatureMarkers(a || '').toLowerCase();
  const y = stripFeatureMarkers(b || '').toLowerCase();
  if (!x || !y) return false;
  if (x === y) return true;
  if (x.includes(y) || y.includes(x)) {
    return Math.min(x.length, y.length) / Math.max(x.length, y.length) > 0.55;
  }
  return false;
}

function isValidFeatureParent(parent) {
  if (!parent || parent.length < 2) return false;
  if (/^P[012]$/.test(parent)) return false;
  if (/^\d+(\.\d+)*$/.test(parent)) return false;
  return true;
}

/** 是否已含可拆成「父 - 子」的路徑 */
export function hasFeaturePathDelimiter(feat) {
  const text = stripFeatureMarkers(feat || '');
  if (!text) return false;
  const m = FEATURE_PATH_DELIMITER_RE.exec(text);
  if (!m || m.index === undefined) return false;
  const parent = text.slice(0, m.index).trim();
  const child = text.slice(m.index + m[0].length).trim();
  return isValidFeatureParent(parent) && !!child;
}

function cleanSourceSegment(seg) {
  let s = (seg || '').trim();
  if (!s || /^(無|—|-)$/i.test(s)) return '';

  if (/^P\d+$/i.test(s)) return '';
  if (/^第\s*\d+\s*頁/.test(s)) return '';
  if (/\.(pdf|docx|xlsx|csv)$/i.test(s)) return '';

  s = s.replace(/^[\w\u4e00-\u9fff]*PRD[_\w]*/i, '').trim();
  s = s.replace(/^\d+(\.\d+)*\.?\s*/, '');

  const labeled = s.match(
    /(?:頁面[^：:]{0,12}|分面[^：:]{0,12}|章節[^：:]{0,8}|模块|模組|section)[：:]\s*(.+)/i
  );
  if (labeled) s = labeled[1].trim();
  else {
    const colon = s.match(/^[^：:]{1,24}[：:]\s*(.{2,})$/);
    if (colon) s = colon[1].trim();
  }

  s = s.replace(/[,，]\s*P\d+.*$/i, '').trim();
  s = s.replace(/\s*[,，]\s*第\s*\d+\s*頁.*$/i, '').trim();

  if (s.length < 2) return '';
  if (/^P\d+$/i.test(s)) return '';
  return s;
}

/** 從規格來源字串拆出有意義的章節片段 */
export function parseSpecSourceSegments(rawSrc) {
  if (!rawSrc || /^(無|—|-)$/i.test(rawSrc.trim())) return [];

  const parts = rawSrc
    .split(/[/\\|｜]/)
    .flatMap(chunk => chunk.split(/\s+-\s+/))
    .map(cleanSourceSegment)
    .filter(Boolean);

  return parts.filter((p, i) => {
    if (i === 0 && /PRD|規格書|规格/i.test(p) && p.length <= 36) return false;
    if (i === 0 && /^玩家管理/.test(p) && p.length <= 28) return false;
    return true;
  });
}

function enrichFromSpecSource(feat, rawSrc) {
  const segs = parseSpecSourceSegments(rawSrc);
  if (segs.length < 2) return null;

  const leafSeg = segs[segs.length - 1];
  let parentSeg = applyL2Alias(segs[segs.length - 2]);

  if (featureSimilar(feat, leafSeg) && parentSeg && !featureSimilar(feat, parentSeg)) {
    return `${parentSeg} - ${stripFeatureMarkers(feat)}`;
  }

  if (segs.length >= 3) {
    const altParent = applyL2Alias(segs[segs.length - 3]);
    if (featureSimilar(feat, leafSeg) && altParent && !featureSimilar(feat, altParent)) {
      return `${altParent} - ${stripFeatureMarkers(feat)}`;
    }
  }

  for (let i = segs.length - 2; i >= 0; i--) {
    const parent = applyL2Alias(segs[i]);
    if (!isValidFeatureParent(parent) || featureSimilar(feat, parent)) continue;
    if (featureSimilar(feat, leafSeg) || i === segs.length - 2) {
      return `${parent} - ${stripFeatureMarkers(feat)}`;
    }
  }

  return null;
}

function enrichFromOutline(feat, mainMod, outline, tier) {
  const main = normalizeMainModule(mainMod || '');
  const f = stripFeatureMarkers(feat || '');
  if (!f || !outline?.items?.length) return null;

  const items = outline.items.filter(it => normalizeMainModule(it.main) === main);
  const l2Items = items.filter(it => it.tier === 'L2');
  const l3Items = items.filter(it => it.tier === 'L3');

  for (const it of l3Items) {
    if (!featureSimilar(f, it.name)) continue;
    const parent = applyL2Alias(it.l2 || '');
    if (parent && !featureSimilar(f, parent)) {
      return `${parent} - ${f}`;
    }
  }

  if (normalizeTierLevel(tier) === 'L3' || l3Items.some(it => featureSimilar(f, it.name))) {
    for (const l2 of l2Items) {
      const l2n = applyL2Alias(stripFeatureMarkers(l2.name));
      const children = l3Items.filter(c => c.l2 === l2.name || c.l2 === l2.l2);
      if (!children.length) continue;
      if (children.some(c => featureSimilar(f, c.name))) {
        return `${l2n} - ${f}`;
      }
    }
  }

  for (const l2 of l2Items) {
    const l2n = applyL2Alias(stripFeatureMarkers(l2.name));
    if (featureSimilar(f, l2n)) return null;
    if (f.includes(l2n) && f.length > l2n.length + 2) {
      const rest = f.slice(f.indexOf(l2n) + l2n.length).replace(/^[\s\-–—/：:]+/, '').trim();
      if (rest.length >= 2) return `${l2n} - ${rest}`;
    }
  }

  return null;
}

function extractFeatureMarkers(featRaw) {
  const m = (featRaw || '').match(/\s*\[(新增|變更|AI自創)\]\s*$/);
  return m ? ` [${m[1]}]` : '';
}

/**
 * 扁平功能名補成「L2 - 子項」供心智圖分層；已有路徑則原樣返回。
 */
export function enrichFeaturePath(featRaw, { mainMod, rawSrc, outline, tier } = {}) {
  const marker = extractFeatureMarkers(featRaw);
  const base = stripFeatureMarkers(featRaw || '');
  if (!base) return featRaw || '';
  if (hasFeaturePathDelimiter(base)) return featRaw;

  const fromSrc = enrichFromSpecSource(base, rawSrc);
  if (fromSrc && hasFeaturePathDelimiter(fromSrc)) {
    return `${fromSrc}${marker}`;
  }

  const fromOutline = enrichFromOutline(base, mainMod, outline, tier);
  if (fromOutline && hasFeaturePathDelimiter(fromOutline)) {
    return `${fromOutline}${marker}`;
  }

  return featRaw;
}

/** 規格來源補上檔名（新舊規格比對／全量產出後處理） */
export function enrichSpecSource(rawSrc, filename) {
  const src = (rawSrc || '').trim();
  const name = (filename || '').trim();
  if (!name || !src || /^(無|—|-)$/i.test(src)) return src;

  const nameLower = name.toLowerCase();
  const stem = name.replace(/\.(pdf|docx|xlsx|csv)$/i, '').toLowerCase();
  const srcLower = src.toLowerCase();

  if (srcLower.includes(nameLower)) return src;
  if (stem.length >= 3 && srcLower.includes(stem)) return src;

  return `${name} / ${src}`;
}

/**
 * 多規格：僅補缺檔名；若來源已含某份 PRD 檔名則不動；多份且無法判斷時不猜。
 */
export function enrichSpecSourceForMulti(rawSrc, docNames) {
  const src = (rawSrc || '').trim();
  if (!src || /^(無|—|-)$/i.test(src) || !docNames?.length) return src;

  const srcLower = src.toLowerCase();
  for (const name of docNames) {
    const n = (name || '').trim();
    if (!n) continue;
    const nameLower = n.toLowerCase();
    const stem = n.replace(/\.(pdf|docx|xlsx|csv)$/i, '').toLowerCase();
    if (srcLower.includes(nameLower)) return src;
    if (stem.length >= 3 && srcLower.includes(stem)) return src;
  }

  if (docNames.length === 1) return enrichSpecSource(src, docNames[0]);
  return src;
}

/** 多規格：依規格來源文字對應到單份 PRD 的 wrapped 文字（供 XLSX 列→工作表補全） */
export function pickWrappedSpecTextForSource(rawSrc, supplementDocs) {
  if (!supplementDocs?.length) return null;
  const srcLower = (rawSrc || '').toLowerCase();

  for (const doc of supplementDocs) {
    const name = (doc.name || '').trim();
    if (!name) continue;
    const nameLower = name.toLowerCase();
    const stem = name.replace(/\.(pdf|docx|xlsx|csv)$/i, '').toLowerCase();
    if (srcLower.includes(nameLower) || (stem.length >= 3 && srcLower.includes(stem))) {
      const body = (doc.text || '').trim();
      return body ? `【規格書：${name}】\n${body}` : null;
    }
  }

  if (supplementDocs.length === 1) {
    const doc = supplementDocs[0];
    const body = (doc.text || '').trim();
    return body ? `【規格書：${doc.name}】\n${body}` : null;
  }
  return null;
}

/** 從已提取的規格文字建立「列號 → 工作表名」索引 */
export function buildXlsxRowSheetIndex(specText) {
  const rowToSheet = new Map();
  const sheets = new Set();
  let currentSheet = null;

  for (const line of (specText || '').split(/\r?\n/)) {
    const sheetM = line.match(/^【工作表：(.+)】\s*$/);
    if (sheetM) {
      currentSheet = sheetM[1].trim();
      if (currentSheet) sheets.add(currentSheet);
      continue;
    }
    const rowM = line.match(/^【列\s*(\d+)】/);
    if (rowM && currentSheet) {
      const row = rowM[1];
      const prev = rowToSheet.get(row);
      if (prev === undefined) rowToSheet.set(row, currentSheet);
      else if (prev !== currentSheet) rowToSheet.set(row, null);
    }
  }

  return { rowToSheet, sheets: [...sheets] };
}

let _xlsxIndexCache = { key: '', index: null };

function getXlsxIndex(specText) {
  if (!specText || !specText.includes('【工作表：')) return null;
  if (_xlsxIndexCache.key === specText) return _xlsxIndexCache.index;
  const index = buildXlsxRowSheetIndex(specText);
  _xlsxIndexCache = { key: specText, index };
  return index;
}

/** 規格來源是否為「檔名 / 列 N」而缺少工作表名 */
function xlsxSourceNeedsSheet(src) {
  const parts = src.split(/\s*\/\s*/).map(p => p.trim()).filter(Boolean);
  const rowIdx = parts.findIndex(p => /^列\s*\d+/.test(p));
  if (rowIdx < 0) return false;
  return rowIdx === 1;
}

/** XLSX 規格來源補上工作表名：檔名 / 工作表 / 列 N */
export function enrichXlsxSpecSource(rawSrc, specText) {
  const src = (rawSrc || '').trim();
  if (!src || /^(無|—|-)$/i.test(src)) return src;
  if (!xlsxSourceNeedsSheet(src)) return src;

  const index = getXlsxIndex(specText);
  if (!index) return src;

  const rowM = src.match(/列\s*(\d+)/);
  if (!rowM) return src;

  const row = rowM[1];
  let sheet = index.rowToSheet.get(row);
  if (!sheet && index.sheets.length === 1) sheet = index.sheets[0];
  if (!sheet) return src;

  return src.replace(/^(.+?)\s*\/\s*(列\s*\d+.*)$/i, `$1 / ${sheet} / $2`);
}

function escapeRegExp(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/** 是否為模組索引檔段落（大平台 - 後台模組內容 … .pdf） */
function isModuleIndexSegment(seg, indexNames = []) {
  const s = (seg || '').trim();
  if (!s) return false;
  if (/模組內容/i.test(s) && /\.pdf/i.test(s)) return true;
  if (/^大平台\s*[-–—]/i.test(s) && /\.pdf/i.test(s)) return true;
  for (const name of indexNames) {
    const n = (name || '').trim();
    if (!n) continue;
    if (s.toLowerCase().includes(n.toLowerCase())) return true;
    const stem = n.replace(/\.(pdf|docx|xlsx|csv)$/i, '');
    if (stem.length >= 4 && s.toLowerCase().includes(stem.toLowerCase()) && /\.pdf/i.test(s)) return true;
  }
  return false;
}

function stripModuleIndexFromSegment(seg, indexNames = []) {
  let s = (seg || '').trim();
  if (!s) return '';
  // 規格書本體（xlsx/csv/docx）不可當模組索引剝除
  if (/\.(xlsx|csv|docx)$/i.test(s)) return s;

  s = s.replace(/\s*大平台\s*[-–—]\s*後台模組內容[^/\\|｜]*\.pdf/gi, '').trim();
  s = s.replace(/\s*[^/\\|｜]*模組內容[^/\\|｜]*\.pdf/gi, '').trim();

  for (const name of indexNames) {
    const n = (name || '').trim();
    if (!n) continue;
    // 僅剝模組索引 PDF，不剝功能規格書檔名
    if (!/\.pdf$/i.test(n) && !/模組內容/i.test(n)) continue;
    s = s.replace(new RegExp(`\\s*${escapeRegExp(n)}`, 'gi'), '').trim();
    const stem = n.replace(/\.(pdf|docx|xlsx|csv)$/i, '');
    if (stem.length >= 4) {
      s = s.replace(
        new RegExp(`\\s*${escapeRegExp(stem)}[^/\\|｜]*\\.pdf`, 'gi'),
        ''
      ).trim();
    }
  }

  if (isModuleIndexSegment(s, indexNames)) return '';
  return s;
}

function looksLikeFeatureOnlySegment(seg) {
  const s = (seg || '').trim();
  if (!s) return false;
  if (/\.(pdf|docx|xlsx|csv)/i.test(s)) return false;
  if (/PRD/i.test(s)) return false;
  if (/^\d+(\.\d+)*\.?\s/.test(s)) return false;
  if (/第\s*\d+\s*頁/.test(s)) return false;
  if (/頁面[^：:]{0,12}[：:]/.test(s)) return false;
  if (/組件[^：:]{0,12}[：:]/.test(s)) return false;
  return true;
}

/**
 * 心智圖卡片顯示用：移除模組索引檔名，保留 PRD 檔名與章節。
 * @param {string} rawSrc
 * @param {string[]} [indexNames] 上傳的模組索引檔名（可選）
 */
export function formatMindmapSpecSource(rawSrc, indexNames = []) {
  const src = (rawSrc || '').trim();
  if (!src || /^(無|—|-)$/i.test(src)) return src;

  let parts = src
    .split(/[/\\|｜]/)
    .map(p => stripModuleIndexFromSegment(p, indexNames))
    .filter(Boolean);

  const hasTableSpecFile = parts.some(p => /\.(xlsx|csv)/i.test(p));

  // XLSX/CSV 表格溯源（檔名 / 工作表 / 列 N）完整保留
  if (hasTableSpecFile && parts.length >= 2) {
    return parts.join(' / ').trim();
  }

  if (parts.length > 1 && !hasTableSpecFile && looksLikeFeatureOnlySegment(parts[0])) {
    parts = parts.slice(1);
  }

  const out = parts.join(' / ').trim();
  return out || src;
}
