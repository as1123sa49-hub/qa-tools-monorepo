/**
 * 多規格模式：優先依模組索引分類，對不上再退回規格書章節 outline
 */
import { normalizeMainModule, stripFeatureMarkers } from './case-utils.js';
import {
  hasFeaturePathDelimiter,
  parseSpecSourceSegments,
  enrichFeaturePath,
} from './feature-path.js';

const L2_ALIASES = {
  '玩家資訊板': '玩家儀表板',
  '玩家信息板': '玩家儀表板',
  '玩家帳號看板': '玩家儀表板',
  '資訊板': '玩家儀表板',
  '信息板': '玩家儀表板',
};

function applyL2Alias(name) {
  return L2_ALIASES[(name || '').trim()] || (name || '').trim();
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

/** 合併索引 outline 與規格書 outline（索引優先、去重） */
export function mergeSpecOutlines(...outlines) {
  const items = [];
  const seen = new Set();
  let order = 0;
  const mainOrder = [];

  for (const outline of outlines) {
    if (!outline?.items?.length) continue;
    for (const m of outline.mainOrder || []) {
      if (!mainOrder.includes(m)) mainOrder.push(m);
    }
    for (const it of outline.items) {
      const key = `${it.main}|${it.tier}|${it.name}`;
      if (seen.has(key)) continue;
      seen.add(key);
      items.push({ ...it, order: order++ });
    }
  }
  return { mainOrder, items };
}

/**
 * 嘗試將案例對上模組索引中的節點
 * @returns {{ mainMod: string, featRaw: string } | null}
 */
export function matchIndexClassification(featRaw, rawSrc, testTitle, indexOutline) {
  if (!indexOutline?.items?.length) return null;

  const feat = stripFeatureMarkers(featRaw || '');
  const title = (testTitle || '').trim();
  const srcSegs = parseSpecSourceSegments(rawSrc);
  const candidates = [...new Set([feat, title, ...srcSegs].filter(Boolean))];

  const l2Items = indexOutline.items.filter(it => it.tier === 'L2');
  const l3Items = indexOutline.items.filter(it => it.tier === 'L3');

  let hitL3 = null;
  let hitL2 = null;

  for (const it of l3Items) {
    const n = stripFeatureMarkers(it.name);
    if (candidates.some(c => featureSimilar(c, n))) {
      hitL3 = it;
      hitL2 = l2Items.find(l2 => l2.name === it.l2 || l2.l2 === it.l2) || null;
      break;
    }
  }

  if (!hitL2) {
    for (const it of l2Items) {
      const n = applyL2Alias(stripFeatureMarkers(it.name));
      if (candidates.some(c => featureSimilar(c, n) || featureSimilar(c, it.name))) {
        hitL2 = it;
        break;
      }
    }
  }

  if (!hitL2 && !hitL3) {
    for (const it of l2Items) {
      const n = applyL2Alias(stripFeatureMarkers(it.name));
      if (candidates.some(c => c.includes(n) && c.length > n.length + 1)) {
        hitL2 = it;
        break;
      }
    }
  }

  const anchor = hitL3 || hitL2;
  if (!anchor) return null;

  const mainMod = normalizeMainModule(anchor.main);
  const marker = (featRaw || '').match(/\s*\[(新增|變更|AI自創)\]\s*$/)?.[0] || '';

  if (hasFeaturePathDelimiter(feat)) {
    return { mainMod, featRaw: featRaw || feat };
  }

  if (hitL2 && hitL3) {
    const l2n = applyL2Alias(stripFeatureMarkers(hitL2.name));
    const l3n = stripFeatureMarkers(hitL3.name);
    const leaf = featureSimilar(feat, l3n) ? feat : (featureSimilar(feat, l2n) ? title || feat : feat);
    if (!featureSimilar(leaf, l2n)) {
      return { mainMod, featRaw: `${l2n} - ${leaf}${marker}` };
    }
  }

  if (hitL2) {
    const l2n = applyL2Alias(stripFeatureMarkers(hitL2.name));
    if (!featureSimilar(feat, l2n)) {
      const leaf = feat || title;
      return { mainMod, featRaw: `${l2n} - ${leaf}${marker}` };
    }
    return { mainMod, featRaw: `${l2n}${marker}` };
  }

  return { mainMod, featRaw: featRaw || feat };
}

/**
 * 多規格案例正規化：索引優先 → 規格書章節 fallback
 */
export function classifyMultiSpecFeature(featRaw, entry, indexOutline, contentOutline, mainMod, tier) {
  const rawSrc = entry['規格來源'] || entry['來源'] || '';
  const idx = matchIndexClassification(featRaw, rawSrc, entry['測試標題'], indexOutline);

  let feat = featRaw;
  let mod = mainMod;

  if (idx) {
    mod = idx.mainMod || mod;
    feat = idx.featRaw || feat;
  }

  feat = enrichFeaturePath(feat, { mainMod: mod, rawSrc, outline: indexOutline, tier });
  if (!hasFeaturePathDelimiter(stripFeatureMarkers(feat))) {
    const alt = enrichFeaturePath(featRaw, { mainMod: mod, rawSrc, outline: contentOutline, tier });
    if (hasFeaturePathDelimiter(stripFeatureMarkers(alt))) feat = alt;
    else if (!hasFeaturePathDelimiter(stripFeatureMarkers(feat))) feat = alt;
  }

  return { mainMod: mod, feat };
}
