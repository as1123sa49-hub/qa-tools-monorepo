/**
 * 案例欄位正規化與排序用常數（多模組共用）
 */

export function getTodayStr() {
  const d = new Date();
  return d.getFullYear().toString() +
    String(d.getMonth() + 1).padStart(2, '0') +
    String(d.getDate()).padStart(2, '0');
}

export function normalizeMainModule(name) {
  const s = (name || '').trim();
  if (!s) return '';
  if (/玩家系統/.test(s)) return '會員系統';
  if (/^KYC/i.test(s) && !/審核/.test(s)) return 'KYC審核';
  return s;
}

export function stripFeatureMarkers(name) {
  return (name || '').replace(/\s*\[(新增|變更|AI自創)\]\s*/g, '').trim();
}

export function normalizeTierLevel(raw) {
  const s = (raw || '').trim().toUpperCase();
  return /^L[123]$/.test(s) ? s : '';
}

export const TIER_SORT = { L1: 0, L2: 1, L3: 2 };
export const PRIO_SORT = { P0: 0, P1: 1, P2: 2 };

export function caseTypeOrder(t) {
  if ((t || '').includes('正面')) return 0;
  if ((t || '').includes('負面')) return 1;
  if ((t || '').includes('邊界')) return 2;
  return 9;
}
