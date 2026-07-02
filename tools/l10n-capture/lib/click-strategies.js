/** 將 canvas 比例換算為畫面像素座標 */
export async function pagePointFromFraction(page, fx, fy) {
  const canvas = page.locator('#unity-canvas');
  const box = await canvas.boundingBox();
  if (!box?.width || !box?.height) return null;
  return {
    pageX: Math.round(box.x + box.width * fx),
    pageY: Math.round(box.y + box.height * fy),
    fx,
    fy,
  };
}

export function clickCandidateKey(c) {
  const x = c.pageX ?? c.x ?? 0;
  const y = c.pageY ?? c.y ?? 0;
  return `${Math.round(x)},${Math.round(y)}`;
}

/** 由 page 座標反推 canvas 內比例（用於寫入 capture-meta） */
export async function inferCanvasFraction(page, pageX, pageY) {
  const canvas = page.locator('#unity-canvas');
  const box = await canvas.boundingBox();
  if (!box?.width || !box?.height) return { fx: null, fy: null };
  return {
    fx: (pageX - box.x) / box.width,
    fy: (pageY - box.y) / box.height,
  };
}

export function isCachedClickNote(note) {
  return note === '快取座標' || note === '快取比例';
}

/** 將 capture-meta 學到的點擊座標優先加入候選（座標優先，否則以比例換算） */
export async function addLearnedCandidate(add, page, learned) {
  if (!learned) return;
  if (learned.pageX != null && learned.pageY != null) {
    await add(learned.pageX, learned.pageY, '快取座標', learned.fx, learned.fy);
  } else if (learned.fx != null && learned.fy != null) {
    const pt = await pagePointFromFraction(page, learned.fx, learned.fy);
    if (pt) await add(pt.pageX, pt.pageY, '快取比例', pt.fx, pt.fy);
  }
}

/** 由成功候選組出寫入 capture-meta 的點擊資訊（缺 fraction 時反推並四捨五入） */
export async function buildLearnedClick(page, candidate) {
  let { fx, fy } = candidate;
  if (fx == null || fy == null) {
    const inferred = await inferCanvasFraction(page, candidate.pageX, candidate.pageY);
    fx = inferred.fx;
    fy = inferred.fy;
  }
  return {
    pageX: candidate.pageX,
    pageY: candidate.pageY,
    fx: fx != null ? Number(fx.toFixed(4)) : undefined,
    fy: fy != null ? Number(fy.toFixed(4)) : undefined,
  };
}

/** 去重候選座標清單 */
export function createCandidateCollector() {
  const candidates = [];
  const seen = new Set();
  const add = async (pageX, pageY, note, fx, fy) => {
    if (!Number.isFinite(pageX) || !Number.isFinite(pageY)) return;
    const key = `${Math.round(pageX)},${Math.round(pageY)}`;
    if (seen.has(key)) return;
    seen.add(key);
    candidates.push({ pageX, pageY, fx, fy, note });
  };
  return { candidates, add };
}

/**
 * 逐候選點擊並以畫面變化驗證；成功回傳 { success: true, ... }，否則 { success: false, lastRatio }。
 */
export async function tryClickCandidates(page, candidates, {
  threshold,
  onLog,
  getBefore,
  click,
  waitAfterClick,
  getAfter,
  measureRatio,
  formatAttemptLog,
  formatSuccessLog,
  formatFailLog,
  onCacheMiss,
}) {
  const tried = new Set();
  let lastRatio = 0;

  for (let i = 0; i < candidates.length; i++) {
    const c = candidates[i];
    const key = clickCandidateKey(c);
    if (tried.has(key)) continue;
    tried.add(key);

    const before = await getBefore(c, i);
    await click(c);
    await waitAfterClick(page, c, i);
    const after = await getAfter(page, c, i);
    lastRatio = await measureRatio(before, after, c);
    onLog?.(formatAttemptLog(c, lastRatio, threshold));

    if (lastRatio >= threshold) {
      onLog?.(formatSuccessLog(c));
      return { success: true, candidate: c, before, after, lastRatio };
    }

    if (isCachedClickNote(c.note)) {
      await onCacheMiss?.(c);
    }
    onLog?.(formatFailLog(c, i, candidates.length));
  }

  return { success: false, lastRatio };
}
