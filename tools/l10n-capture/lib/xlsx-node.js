import ExcelJS from 'exceljs';

const KEY_COLUMN = 'Key';

/** @param {string} header */
export function parseLangFromHeader(header) {
  const h = String(header || '').trim();
  if (!h || h.toLowerCase() === KEY_COLUMN.toLowerCase()) return null;
  const m = h.match(/\(([^)]+)\)\s*$/);
  return m ? m[1].trim() : null;
}

/** @param {string} header @returns {{ code: string, header: string, label: string } | null} */
export function parseLangColumn(header) {
  const code = parseLangFromHeader(header);
  if (!code) return null;
  const h = String(header || '').trim();
  const label = h.replace(/\([^)]+\)\s*$/, '').trim() || code;
  return { code, header: h, label };
}

/** @param {string[]} headers */
export function listLangsFromHeaders(headers) {
  const map = new Map();
  for (const header of headers) {
    const col = parseLangColumn(header);
    if (col && !map.has(col.code)) map.set(col.code, col);
  }
  return [...map.values()].sort((a, b) => a.code.localeCompare(b.code));
}

function expandLocalizationFromTable(headers, rows) {
  if (!headers.length) return [];
  const keyIdx = headers.findIndex(h => h.trim().toLowerCase() === 'key');
  if (keyIdx < 0) throw new Error('找不到 Key 欄位，請確認第一列包含 Key');

  const langCols = headers
    .map((header, idx) => ({ header, idx, lang: parseLangFromHeader(header) }))
    .filter(col => col.lang && col.idx !== keyIdx);

  if (!langCols.length) {
    throw new Error('找不到語系欄位，欄名需含括號代碼，例如 Bangla(bn)');
  }

  const items = [];
  for (const row of rows) {
    const key = String(row[keyIdx] || '').trim();
    if (!key) continue;
    for (const col of langCols) {
      const expectedText = String(row[col.idx] || '').trim();
      if (!expectedText) continue;
      items.push({ key, lang: col.lang, langLabel: col.header, expectedText });
    }
  }
  return items;
}

function safeCellText(cell) {
  if (!cell || cell.value == null) return '';
  const v = cell.value;
  if (typeof v === 'object') {
    if (Array.isArray(v.richText)) {
      return v.richText.map(rt => rt.text || '').join('');
    }
    if (v.text != null) return String(v.text);
    if (v.result != null) return String(v.result);
    if (v.hyperlink) return String(v.text || v.hyperlink);
  }
  return String(v);
}

/**
 * @param {Buffer|ArrayBuffer} data
 * @returns {Promise<Array<{ code: string, header: string, label: string }>>}
 */
export async function listLangsFromXlsx(data) {
  const wb = new ExcelJS.Workbook();
  await wb.xlsx.load(data);
  const map = new Map();
  for (const ws of wb.worksheets) {
    const headerRow = ws.getRow(1);
    if (!headerRow) continue;
    const headers = [];
    let maxCol = 0;
    headerRow.eachCell({ includeEmpty: true }, (cell, col) => {
      maxCol = Math.max(maxCol, col);
      headers[col - 1] = safeCellText(cell).trim();
    });
    for (let c = 0; c < maxCol; c++) {
      const col = parseLangColumn(headers[c] || '');
      if (col && !map.has(col.code)) map.set(col.code, col);
    }
  }
  return [...map.values()].sort((a, b) => a.code.localeCompare(b.code));
}

/**
 * @param {Buffer|ArrayBuffer} data
 * @returns {Promise<string[]>}
 */
export async function listSheetNames(data) {
  const wb = new ExcelJS.Workbook();
  await wb.xlsx.load(data);
  return wb.worksheets.map(ws => ws.name);
}

/**
 * @param {Buffer|ArrayBuffer} data
 * @param {string} sheetName
 */
export async function loadKeysFromSheet(data, sheetName, lang = 'bn') {
  const wb = new ExcelJS.Workbook();
  await wb.xlsx.load(data);
  const ws = wb.getWorksheet(sheetName);
  if (!ws) throw new Error(`找不到工作表：${sheetName}`);

  const headers = [];
  const headerRow = ws.getRow(1);
  if (!headerRow) throw new Error('工作表為空');

  let maxCol = 0;
  headerRow.eachCell({ includeEmpty: true }, (cell, col) => {
    maxCol = Math.max(maxCol, col);
    headers[col - 1] = safeCellText(cell).trim();
  });

  const normalizedHeaders = [];
  for (let c = 0; c < maxCol; c++) {
    normalizedHeaders.push(headers[c] || '');
  }

  const dataRows = [];
  ws.eachRow({ includeEmpty: false }, (row, rowNumber) => {
    if (rowNumber === 1) return;
    const cells = [];
    for (let c = 1; c <= maxCol; c++) {
      cells.push(safeCellText(row.getCell(c)).trim());
    }
    dataRows.push(cells);
  });

  const items = expandLocalizationFromTable(normalizedHeaders, dataRows);
  const filtered = items.filter(i => i.lang === lang);
  return { sheetName, keys: filtered.map(i => i.key), items: filtered };
}
