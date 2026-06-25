/**
 * 多規格模式：手動模組索引（對照大平台模組 PDF 表格）
 */
import { normalizeMainModule } from './case-utils.js';

export const MANUAL_INDEX_STORAGE_KEY = 'multi_manual_index_rows';

/** L1 對照：PDF 常寫玩家管理，案例主模組用會員系統 */
export function normalizeManualL1(name) {
  const s = (name || '').trim();
  if (!s) return '';
  if (/玩家系統|玩家管理|player\s*management/i.test(s)) return '會員系統';
  const norm = normalizeMainModule(s);
  return norm || s;
}

export function isValidManualIndexRows(rows) {
  return (rows || []).some(r => {
    if (!normalizeManualL1(r.l1) || !(r.l2 || '').trim()) return false;
    return true;
  });
}

/** L3 文字框：每行一個細項 */
export function splitManualL3Lines(l3Text) {
  return (l3Text || '')
    .split(/\r?\n/)
    .map(s => s.trim())
    .filter(Boolean);
}

/** 建 lastIndexOutline（含 L3 → 父 L2 連結） */
export function buildOutlineFromManualRows(rows) {
  const mainOrder = [];
  const items = [];
  const l2Keys = new Set();
  let order = 0;
  const seenL1 = new Set();

  for (const row of rows || []) {
    const main = normalizeManualL1(row.l1);
    const l2 = (row.l2 || '').trim();
    const l3Lines = splitManualL3Lines(row.l3);
    if (!main || !l2) continue;

    if (!mainOrder.includes(main)) mainOrder.push(main);
    if (!seenL1.has(main)) {
      seenL1.add(main);
      items.push({ main, tier: 'L1', name: main, l2: null, order: order++ });
    }

    const l2Key = `${main}::${l2}`;
    if (l3Lines.length) {
      if (!l2Keys.has(l2Key)) {
        l2Keys.add(l2Key);
        items.push({ main, tier: 'L2', name: l2, l2, order: order++ });
      }
      for (const l3 of l3Lines) {
        items.push({ main, tier: 'L3', name: l3, l2, order: order++ });
      }
    } else {
      if (!l2Keys.has(l2Key)) l2Keys.add(l2Key);
      items.push({ main, tier: 'L2', name: l2, l2, order: order++ });
    }
  }
  return { mainOrder, items };
}

/** 送進 prompt 的索引文字（仿 PDF 列格式） */
export function formatManualIndexForPrompt(rows) {
  const lines = [
    '【手動模組索引（對照大平台模組表）】',
    'L1=主模組、L2=頁面功能群、L3=元件細項（選填，可多行）',
    '',
  ];
  for (const row of rows || []) {
    const main = normalizeManualL1(row.l1);
    const l2 = (row.l2 || '').trim();
    const l3Lines = splitManualL3Lines(row.l3);
    const note = (row.note || '').trim();
    if (!main || !l2) continue;
    if (l3Lines.length) {
      for (const l3 of l3Lines) {
        lines.push(`[L3 元件] ${main} / ${l2} / ${l3}${note ? ` — ${note}` : ''}`);
      }
    } else {
      lines.push(`[L2 頁面] ${main} / ${l2}${note ? ` — ${note}` : ''}`);
    }
  }
  return lines.join('\n');
}

export function loadManualIndexRows() {
  try {
    const raw = localStorage.getItem(MANUAL_INDEX_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return null;
    return parsed.map(r => ({
      l1: r.l1 || '',
      l2: r.l2 || '',
      l3: r.l3 || '',
      note: r.note || '',
      collapsed: r.collapsed === true,
    }));
  } catch (_) {
    return null;
  }
}

export function saveManualIndexRows(rows) {
  localStorage.setItem(MANUAL_INDEX_STORAGE_KEY, JSON.stringify(rows || []));
}

export const DEFAULT_MANUAL_INDEX_ROWS = [
  { l1: '', l2: '', l3: '', note: '' },
  { l1: '', l2: '', l3: '', note: '' },
];
