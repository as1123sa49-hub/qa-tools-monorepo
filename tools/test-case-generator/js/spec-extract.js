/** 規格書多格式提取（PDF / DOCX / XLSX / CSV） */

export const SPEC_ACCEPT = '.pdf,.docx,.xlsx,.csv';

export const SKIP_SHEET_KEYWORDS = [
  '日誌', 'changelog', '更新紀錄', '修訂', '版本紀錄',
  '競品', '參考', 'reference', '封面', '目錄', 'readme', '說明'
];

const OBSOLETE_CELL_KEYWORDS = ['隱藏', '廢棄', '作廢', 'deprecated', 'deleted', '刪除'];
const WNS = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main';
const HEADING_STYLES = new Set([
  'heading1', 'heading2', 'heading3', 'heading4', 'title', 'subtitle',
  '1', '2', '3', '4'
]);

export function isSpecFile(file) {
  return !!getSpecFormat(file);
}

export function getSpecFormat(file) {
  const n = (file?.name || '').toLowerCase();
  if (n.endsWith('.pdf')) return 'pdf';
  if (n.endsWith('.docx')) return 'docx';
  if (n.endsWith('.xlsx')) return 'xlsx';
  if (n.endsWith('.csv')) return 'csv';
  return null;
}

export function getSpecFileKey(file) {
  return `${file.name}|${file.size}|${file.lastModified}`;
}

export function suggestSkipSheet(sheetName) {
  const lower = (sheetName || '').toLowerCase();
  return SKIP_SHEET_KEYWORDS.some(kw => {
    const k = kw.toLowerCase();
    return lower.includes(k) || (sheetName || '').includes(kw);
  });
}

function parseCsvLine(line) {
  const out = [];
  let cur = '';
  let q = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (ch === '"') {
      if (q && line[i + 1] === '"') { cur += '"'; i++; }
      else q = !q;
    } else if (ch === ',' && !q) {
      out.push(cur.trim());
      cur = '';
    } else {
      cur += ch;
    }
  }
  out.push(cur.trim());
  return out;
}

function normalizeHeaderName(name) {
  if (name == null) return '';
  return String(name)
    .replace(/^\uFEFF/, '')
    .replace(/\r|\n/g, '')
    .replace(/\u3000/g, ' ')
    .trim();
}

function safeCellText(cell) {
  if (!cell) return '';
  try {
    const v = cell.value;
    if (v == null) return '';
    if (typeof v === 'object' && v.richText) {
      return v.richText.map(r => r.text || '').join('');
    }
    if (v instanceof Date) {
      return v.toISOString().slice(0, 10);
    }
    if (typeof v === 'object' && v.text != null) return String(v.text);
    return String(v);
  } catch {
    try {
      return cell.text ? String(cell.text) : '';
    } catch {
      return '';
    }
  }
}

function isObsoleteRowValue(val) {
  const s = (val || '').toLowerCase();
  return OBSOLETE_CELL_KEYWORDS.some(kw => s.includes(kw.toLowerCase()));
}

function rowLooksObsolete(headers, values) {
  for (let i = 0; i < headers.length; i++) {
    const h = (headers[i] || '').toLowerCase();
    const v = values[i] || '';
    if (/狀態|status|入口/.test(h) && isObsoleteRowValue(v)) return true;
  }
  return values.some(v => isObsoleteRowValue(v) && /廢棄|作廢|deprecated/i.test(v));
}

function formatTableRow(headers, values, rowLabel) {
  const parts = [];
  for (let i = 0; i < headers.length; i++) {
    const h = headers[i];
    const v = (values[i] || '').trim();
    if (!h && !v) continue;
    if (!v || v === '-') continue;
    parts.push(`${h || `欄${i + 1}`}=${v}`);
  }
  if (!parts.length) return '';
  return `【${rowLabel}】${parts.join('；')}`;
}

function looksLikeNumberedHeading(text) {
  const t = (text || '').trim();
  if (!t || t.length > 48) return false;
  if (/^(?:\d+\.){1,4}\d*\s+\S/.test(t)) return true;
  if (/^第[一二三四五六七八九十百千\d]+[章节節][：:\s]/.test(t)) return true;
  return false;
}

function maybeHeadingPrefix(styleVal, text) {
  const s = (styleVal || '').toLowerCase();
  if (!text.trim()) return '';
  if (HEADING_STYLES.has(s) || /^heading\d/i.test(s) || looksLikeNumberedHeading(text)) {
    return `◆ ${text.trim()}\n`;
  }
  return `${text.trim()}\n`;
}

// ─── PDF ─────────────────────────────────────────────────────
export async function extractPdfText(file) {
  const pdfjsLib = window.pdfjsLib;
  if (!pdfjsLib) throw new Error('PDF 解析元件未載入');
  const arrayBuffer = await file.arrayBuffer();
  const pdf = await pdfjsLib.getDocument({ data: arrayBuffer }).promise;
  let fullText = '';
  for (let i = 1; i <= pdf.numPages; i++) {
    const page = await pdf.getPage(i);
    const content = await page.getTextContent();
    const pageText = content.items.map(item => item.str).join(' ');
    fullText += `\n--- 第 ${i} 頁 ---\n${pageText}`;
  }
  return fullText;
}

// ─── DOCX ────────────────────────────────────────────────────
function childrenByLocal(el, name) {
  return Array.from(el?.children || []).filter(c => c.localName === name);
}

function textFromRun(run) {
  return childrenByLocal(run, 't').map(t => t.textContent || '').join('');
}

function isStrikeRun(run) {
  const rPr = childrenByLocal(run, 'rPr')[0];
  if (!rPr) return false;
  return childrenByLocal(rPr, 'strike').length > 0 || childrenByLocal(rPr, 'dstrike').length > 0;
}

function getWVal(el) {
  if (!el) return '';
  return el.getAttributeNS(WNS, 'val') || el.getAttribute('w:val') || el.getAttribute('val') || '';
}

function paragraphStyleVal(p) {
  const pPr = childrenByLocal(p, 'pPr')[0];
  const pStyle = pPr ? childrenByLocal(pPr, 'pStyle')[0] : null;
  return getWVal(pStyle);
}

function extractParagraphText(p, stats) {
  const parts = [];
  for (const child of p.children) {
    if (child.localName === 'r') {
      if (isStrikeRun(child)) {
        const t = textFromRun(child);
        if (t.trim()) stats.strikeRuns++;
        continue;
      }
      const t = textFromRun(child);
      if (t) parts.push(t);
    } else if (child.localName === 'del') {
      stats.strikeRuns++;
    }
  }
  const text = parts.join('');
  if (!text.trim()) return '';
  return maybeHeadingPrefix(paragraphStyleVal(p), text);
}

function extractTableText(tbl, stats) {
  const lines = [];
  for (const tr of childrenByLocal(tbl, 'tr')) {
    const cells = [];
    for (const tc of childrenByLocal(tr, 'tc')) {
      let cellText = '';
      for (const p of childrenByLocal(tc, 'p')) {
        cellText += extractParagraphText(p, stats).replace(/\n$/, ' ');
      }
      cells.push(cellText.trim());
    }
    const joined = cells.filter(Boolean).join(' | ');
    if (joined) lines.push(joined);
  }
  return lines.length ? `${lines.join('\n')}\n` : '';
}

export async function extractDocxText(file) {
  const JSZip = window.JSZip;
  if (!JSZip) throw new Error('DOCX 解析元件未載入（JSZip）');
  const zip = await JSZip.loadAsync(await file.arrayBuffer());
  const entry = zip.file('word/document.xml');
  if (!entry) throw new Error('DOCX 格式異常：找不到 document.xml');

  const xml = await entry.async('string');
  const doc = new DOMParser().parseFromString(xml, 'application/xml');
  const body = doc.getElementsByTagNameNS(WNS, 'body')[0]
    || doc.getElementsByTagName('body')[0];
  if (!body) throw new Error('DOCX 格式異常：找不到 body');

  const stats = { strikeRuns: 0 };
  let text = '';
  for (const child of body.children) {
    if (child.localName === 'p') {
      text += extractParagraphText(child, stats);
    } else if (child.localName === 'tbl') {
      text += extractTableText(child, stats);
    }
  }

  return {
    text: text.trim(),
    meta: { format: 'docx', skipped: { strikeRuns: stats.strikeRuns } }
  };
}

// ─── XLSX ────────────────────────────────────────────────────
function getExcelJS() {
  const ExcelJS = window.ExcelJS;
  if (!ExcelJS) throw new Error('XLSX 解析元件未載入（ExcelJS）');
  return ExcelJS;
}

export async function listXlsxSheets(file) {
  const wb = new (getExcelJS()).Workbook();
  await wb.xlsx.load(await file.arrayBuffer());
  return wb.worksheets.map(ws => {
    let rowCount = 0;
    ws.eachRow({ includeEmpty: false }, () => { rowCount++; });
    return { name: ws.name, rowCount };
  });
}

function sheetToText(ws, sheetName, stats) {
  const lines = [`【工作表：${sheetName}】`];
  const headers = [];
  const headerRow = ws.getRow(1);
  if (headerRow) {
    headerRow.eachCell({ includeEmpty: false }, (cell, col) => {
      headers[col] = normalizeHeaderName(safeCellText(cell));
    });
  }

  ws.eachRow({ includeEmpty: false }, (row, rowNumber) => {
    if (rowNumber === 1 && headers.some(Boolean)) return;

    const values = [];
    let hasStrike = false;
    row.eachCell({ includeEmpty: true }, (cell, col) => {
      if (cell.font?.strike) hasStrike = true;
      values[col] = safeCellText(cell).trim();
    });
    if (hasStrike) {
      stats.strikeRows++;
      return;
    }

    const rowVals = [];
    const maxCol = Math.max(headers.length, values.length, 0);
    for (let c = 1; c <= maxCol; c++) {
      rowVals.push(values[c] || '');
    }
    const hdrs = [];
    for (let c = 1; c <= maxCol; c++) {
      hdrs.push(headers[c] || `欄${c}`);
    }

    if (rowLooksObsolete(hdrs, rowVals)) {
      stats.obsoleteRows++;
      return;
    }

    const line = formatTableRow(hdrs, rowVals, `列 ${rowNumber}`);
    if (line) lines.push(line);
  });

  if (lines.length <= 1) return '';
  return `${lines.join('\n')}\n`;
}

export async function extractXlsxSpecText(file, selectedSheetNames) {
  const wb = new (getExcelJS()).Workbook();
  await wb.xlsx.load(await file.arrayBuffer());
  const allNames = wb.worksheets.map(ws => ws.name);
  const selected = selectedSheetNames?.length
    ? allNames.filter(n => selectedSheetNames.includes(n))
    : allNames.filter(n => !suggestSkipSheet(n));

  if (!selected.length) {
    throw new Error('請至少選擇一個工作表');
  }

  const stats = { strikeRows: 0, obsoleteRows: 0, sheets: allNames.filter(n => !selected.includes(n)) };
  const segments = [];
  for (const ws of wb.worksheets) {
    if (!selected.includes(ws.name)) continue;
    const chunk = sheetToText(ws, ws.name, stats);
    if (chunk.trim()) segments.push(chunk.trim());
  }

  if (!segments.length) {
    throw new Error('選取的工作表沒有可讀內容');
  }

  return {
    text: segments.join('\n\n'),
    meta: { format: 'xlsx', skipped: stats, sheets: allNames, selected }
  };
}

// ─── CSV（規格用表格）────────────────────────────────────────
export async function extractCsvSpecText(file) {
  const text = await file.text();
  const lines = text.split(/\r?\n/).filter(l => l.trim() !== '');
  if (lines.length < 2) throw new Error('CSV 內容不足，至少需要標題列與 1 筆資料');

  const headers = parseCsvLine(lines[0]).map(normalizeHeaderName);
  const stats = { obsoleteRows: 0 };
  const out = [`【檔案：${file.name}】`];

  for (let i = 1; i < lines.length; i++) {
    const cols = parseCsvLine(lines[i]);
    if (rowLooksObsolete(headers, cols)) {
      stats.obsoleteRows++;
      continue;
    }
    const line = formatTableRow(headers, cols, `列 ${i + 1}`);
    if (line) out.push(line);
  }

  if (out.length <= 1) throw new Error('CSV 沒有有效資料列');

  return {
    text: out.join('\n'),
    meta: { format: 'csv', skipped: stats }
  };
}

// ─── 統一入口 ────────────────────────────────────────────────
export async function extractSpecText(file, options = {}) {
  const format = getSpecFormat(file);
  if (!format) {
    throw new Error('不支援的規格格式，請使用 PDF、DOCX、XLSX 或 CSV');
  }

  if (format === 'pdf') {
    const text = await extractPdfText(file);
    return { text, meta: { format: 'pdf', skipped: {} } };
  }
  if (format === 'docx') return extractDocxText(file);
  if (format === 'xlsx') return extractXlsxSpecText(file, options.selectedSheets);
  if (format === 'csv') return extractCsvSpecText(file);

  throw new Error('不支援的規格格式');
}

export function formatExtractSummary(meta) {
  if (!meta) return '';
  const parts = [];
  if (meta.format) parts.push(meta.format.toUpperCase());
  if (meta.selected?.length) parts.push(`${meta.selected.length} 個工作表`);
  if (meta.skipped?.strikeRuns) parts.push(`略過刪除線 ${meta.skipped.strikeRuns} 段`);
  if (meta.skipped?.strikeRows) parts.push(`略過刪除線列 ${meta.skipped.strikeRows}`);
  if (meta.skipped?.obsoleteRows) parts.push(`略過廢棄列 ${meta.skipped.obsoleteRows}`);
  if (meta.skipped?.sheets?.length) parts.push(`未選工作表 ${meta.skipped.sheets.length}`);
  return parts.join(' · ');
}
