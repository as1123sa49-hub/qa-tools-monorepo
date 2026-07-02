/** Slot015 → 工作表 S015 */

export function slotToSheet(slotId) {
  const m = String(slotId || '').trim().match(/^Slot(\d+)$/i);
  if (!m) throw new Error(`無效的 Slot 格式：${slotId}（應為 Slot015）`);
  return `S${m[1]}`;
}

export function sheetToSlot(sheetName) {
  const m = String(sheetName || '').trim().match(/^S(\d+)$/i);
  if (!m) return null;
  return `Slot${m[1]}`;
}
