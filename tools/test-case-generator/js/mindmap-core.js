import {
  normalizeMainModule,
  stripFeatureMarkers,
  caseTypeOrder,
  PRIO_SORT,
} from './case-utils.js';
import { enrichFeaturePath, formatMindmapSpecSource } from './feature-path.js';

export const MINDMAP_MAIN_ORDER = ['通用功能', '會員系統', '金流系統', 'KYC審核', '遊戲大廳'];

export function isMindmapCaseValid(c) {
  if (c._obsolete) return false;
  const s = (c['狀態'] || '').trim();
  if (!s) return true;
  if (s === '有效') return true;
  return s !== '失效' && !/失效/.test(s);
}

export function stripLeadingStepNumber(text) {
  return (text || '').trim().replace(/^\d+[.)．、]\s*/, '');
}

export function formatMindmapTestAction(c) {
  let title = stripLeadingStepNumber(c['測試標題'] || '');
  let pre = (c['前置條件'] || '').trim();
  if (pre === '無' || pre === '—' || pre === '-') pre = '';
  title = title.replace(/^(驗證|確認|檢查|測試)/, '').trim();
  if (pre && title.length < 24) return `${pre} → ${title}`;
  return title || pre || '—';
}

export function escapeMermaidLabel(text) {
  return (text || '')
    .toString()
    .replace(/"/g, "'")
    .replace(/[\r\n]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function truncateMindmapText(text, maxLen) {
  const s = escapeMermaidLabel(text);
  if (s.length <= maxLen) return s;
  return s.slice(0, maxLen) + '…';
}

function wrapMermaidNode(text) {
  const safe = escapeMermaidLabel(text);
  return `["${safe}"]`;
}

function compareMindmapCases(a, b) {
  const ma = MINDMAP_MAIN_ORDER.indexOf(normalizeMainModule(a['主模組'] || ''));
  const mb = MINDMAP_MAIN_ORDER.indexOf(normalizeMainModule(b['主模組'] || ''));
  if (ma !== mb && (ma >= 0 || mb >= 0)) return (ma < 0 ? 999 : ma) - (mb < 0 ? 999 : mb);
  const fc = stripFeatureMarkers(a['功能頁面/元件'] || '')
    .localeCompare(stripFeatureMarkers(b['功能頁面/元件'] || ''), 'zh-TW', { numeric: true });
  if (fc !== 0) return fc;
  const tya = caseTypeOrder(a['測試類型']);
  const tyb = caseTypeOrder(b['測試類型']);
  if (tya !== tyb) return tya - tyb;
  if ((PRIO_SORT[a['優先度']] ?? 9) !== (PRIO_SORT[b['優先度']] ?? 9)) {
    return (PRIO_SORT[a['優先度']] ?? 9) - (PRIO_SORT[b['優先度']] ?? 9);
  }
  return (a['編號'] || '').localeCompare(b['編號'] || '', 'zh-TW', { numeric: true });
}

const FEATURE_PATH_DELIMITER_RE = /[/\-_]|(?:\s+[-–—]\s+)|(?:\s*[：:]\s+)/;
const FEATURE_PATH_NO_SPLIT_RE = /^Slot_\d+/i;

function findFirstFeatureDelimiter(text) {
  const m = FEATURE_PATH_DELIMITER_RE.exec(text);
  if (!m || m.index === undefined) return null;
  return { index: m.index, length: m[0].length };
}

function isValidFeatureParent(parent) {
  if (!parent || parent.length < 2) return false;
  if (/^P[012]$/.test(parent)) return false;
  if (/^\d+$/.test(parent)) return false;
  return true;
}

export function splitFeatureSegments(cleaned) {
  const text = (cleaned || '').trim() || '未分類';
  if (FEATURE_PATH_NO_SPLIT_RE.test(text)) {
    return { folders: [], caseTitle: text };
  }
  const delim = findFirstFeatureDelimiter(text);
  if (!delim) return { folders: [], caseTitle: text };
  const parent = text.slice(0, delim.index).trim();
  const child = text.slice(delim.index + delim.length).trim();
  if (!isValidFeatureParent(parent) || !child) {
    return { folders: [], caseTitle: text };
  }
  return { folders: [parent], caseTitle: child };
}

function rawFeatHasChildUnder(rawFeat, parentTitle) {
  if (!rawFeat.startsWith(parentTitle) || rawFeat.length <= parentTitle.length) return false;
  const rest = rawFeat.slice(parentTitle.length);
  const delim = findFirstFeatureDelimiter(rest);
  return delim && delim.index === 0;
}

function canonicalFromSegments(folders, caseTitle) {
  return [...(folders || []), caseTitle].filter(Boolean).join('/') || '未分類';
}

function applyPrefixClustering(entries) {
  const byMain = new Map();
  for (const e of entries) {
    if (!byMain.has(e.main)) byMain.set(e.main, []);
    byMain.get(e.main).push(e);
  }
  for (const list of byMain.values()) {
    const folderRoots = new Set();
    for (const e of list) {
      e.parsed.folders.forEach(f => folderRoots.add(f));
    }
    for (const e of list) {
      if (e.parsed.folders.length > 0) continue;
      const title = e.parsed.caseTitle;
      const isPrefixOfOther = list.some(other =>
        other !== e && rawFeatHasChildUnder(other.rawFeat, title)
      );
      if (folderRoots.has(title) || isPrefixOfOther) {
        e.parsed = { folders: [title], caseTitle: '總覽' };
      }
    }
  }
}

function normalizeFeaturePath(featRaw) {
  const rawFeat = stripFeatureMarkers(featRaw || '') || '未分類';
  const parsed = splitFeatureSegments(rawFeat);
  const canonical = canonicalFromSegments(parsed.folders, parsed.caseTitle);
  return { rawFeat, folders: parsed.folders, caseTitle: parsed.caseTitle, canonical, full: canonical };
}

export function parseFeaturePath(featRaw) {
  const n = normalizeFeaturePath(featRaw);
  return { folders: n.folders, caseTitle: n.caseTitle, full: n.canonical };
}

function pickHighestPriority(cases) {
  let best = 'P2';
  for (const c of cases) {
    const m = (c['優先度'] || '').match(/P[012]/);
    const p = m ? m[0] : null;
    if (p && (PRIO_SORT[p] ?? 9) < (PRIO_SORT[best] ?? 9)) best = p;
  }
  return best;
}

function pickFirstNonemptyField(cases, field) {
  for (const c of cases) {
    const v = (c[field] || '').trim();
    if (v && v !== '無' && v !== '—' && v !== '-') return v;
  }
  return '';
}

function buildPlatformCaseFromCanonical(mainModule, canonical, rows, opts = {}) {
  const parts = canonical.split('/').filter(Boolean);
  const folders = parts.length > 1 ? parts.slice(0, -1) : [];
  const caseTitle = parts.length ? parts[parts.length - 1] : '未分類';
  const pre = pickFirstNonemptyField(rows, '前置條件');
  const rawFeatures = [...new Set(rows.map(c => stripFeatureMarkers(c['功能頁面/元件'] || '')).filter(Boolean))];
  const rawDesc = pickFirstNonemptyField(rows, '規格來源');
  return {
    id: `${mainModule}::${canonical}`,
    mainModule,
    folderPath: folders,
    caseTitle,
    fullFeature: canonical,
    rawFeatures,
    priority: pickHighestPriority(rows),
    description: formatMindmapSpecSource(rawDesc, opts.indexNames),
    precondition: pre || '無',
    rowCount: rows.length,
    steps: rows.map(c => ({
      action: stripLeadingStepNumber((c['測試標題'] || formatMindmapTestAction(c) || '—').trim()) || '—',
      expected: (c['預期結果'] || '—').trim(),
      caseId: c['編號'] || ''
    }))
  };
}

function buildPlatformCases(cases, opts = {}) {
  const sorted = [...cases].sort(compareMindmapCases);
  const entries = sorted.map(c => {
    const main = normalizeMainModule(c['主模組'] || '') || '未分類';
    const featRaw = stripFeatureMarkers(c['功能頁面/元件'] || '') || '未分類';
    const enriched = enrichFeaturePath(featRaw, {
      mainMod: main,
      rawSrc: c['規格來源'] || '',
      outline: null,
      tier: c['層級'] || '',
    });
    const rawFeat = stripFeatureMarkers(enriched || featRaw) || '未分類';
    const parsed = splitFeatureSegments(rawFeat);
    return { main, rawFeat, parsed, row: c };
  });
  applyPrefixClustering(entries);
  entries.forEach(e => {
    e.canonical = canonicalFromSegments(e.parsed.folders, e.parsed.caseTitle);
  });
  const groups = new Map();
  for (const e of entries) {
    const key = `${e.main}::${e.canonical}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(e.row);
  }
  return [...groups.entries()].map(([key, rows]) => {
    const sep = key.indexOf('::');
    const main = key.slice(0, sep);
    const canonical = key.slice(sep + 2);
    return buildPlatformCaseFromCanonical(main, canonical, rows, opts);
  });
}

function createNavNode(name, type) {
  return { name, type, children: new Map(), cases: [] };
}

function serializeNavNode(node) {
  const children = [...node.children.entries()]
    .sort((a, b) => a[0].localeCompare(b[0], 'zh-TW', { numeric: true }))
    .map(([, child]) => serializeNavNode(child));
  return {
    name: node.name,
    type: node.type,
    children,
    cases: node.cases.slice().sort((a, b) =>
      a.caseTitle.localeCompare(b.caseTitle, 'zh-TW', { numeric: true })
    )
  };
}

function buildNavTree(platformCases) {
  const roots = new Map();
  for (const pc of platformCases) {
    let root = roots.get(pc.mainModule);
    if (!root) {
      root = createNavNode(pc.mainModule, 'main');
      roots.set(pc.mainModule, root);
    }
    let node = root;
    for (const folder of pc.folderPath) {
      if (!node.children.has(folder)) {
        node.children.set(folder, createNavNode(folder, 'folder'));
      }
      node = node.children.get(folder);
    }
    node.cases.push(pc);
  }
  return [...roots.entries()]
    .sort((a, b) => {
      const ia = MINDMAP_MAIN_ORDER.indexOf(a[0]);
      const ib = MINDMAP_MAIN_ORDER.indexOf(b[0]);
      if (ia !== ib) return (ia < 0 ? 999 : ia) - (ib < 0 ? 999 : ib);
      return a[0].localeCompare(b[0], 'zh-TW');
    })
    .map(([, node]) => serializeNavNode(node));
}

export function buildMindMapTree(cases, opts = {}) {
  const valid = cases.filter(isMindmapCaseValid);
  const platformCases = buildPlatformCases(valid, opts);
  const roots = buildNavTree(platformCases);
  const modules = roots.map(r => ({
    name: r.name,
    caseCount: countRowsInNavNode(r),
    platformCaseCount: countPlatformCasesInNavNode(r)
  }));
  return {
    roots,
    platformCases,
    modules,
    validCount: valid.length,
    skippedCount: cases.length - valid.length,
    platformCaseCount: platformCases.length
  };
}

export function countPlatformCasesInNavNode(node) {
  let n = node.cases.length;
  for (const ch of node.children) n += countPlatformCasesInNavNode(ch);
  return n;
}

export function countRowsInNavNode(node) {
  let n = node.cases.reduce((s, pc) => s + pc.rowCount, 0);
  for (const ch of node.children) n += countRowsInNavNode(ch);
  return n;
}

export function collectPlatformCasesFromNavNode(node) {
  const list = [...node.cases];
  for (const ch of node.children) list.push(...collectPlatformCasesFromNavNode(ch));
  return list;
}

export function findNavNodeByPath(roots, path) {
  if (!path?.length) return null;
  let node = roots.find(r => r.name === path[0]);
  if (!node) return null;
  for (let i = 1; i < path.length; i++) {
    node = node.children.find(c => c.name === path[i]);
    if (!node) return null;
  }
  return node;
}

export function getModulePathLabel(pc) {
  return [pc.mainModule, ...pc.folderPath].filter(Boolean).join(' › ');
}

export function formatPlatformCaseCopy(pc) {
  const path = getModulePathLabel(pc);
  let out = `=== 模組路徑 ===\n${path}\n\n`;
  out += `=== 測試案例 ===\n`;
  out += `標題：${pc.caseTitle}\n`;
  out += `優先度：${pc.priority}\n`;
  out += `案例描述：${pc.description || '無'}\n`;
  out += `前置條件：${pc.precondition || '無'}\n\n`;
  out += `=== 測試步驟 ===\n`;
  pc.steps.forEach((s, i) => {
    out += `${i + 1}. 動作：${s.action}\n   預期：${s.expected}\n`;
  });
  return out;
}

export function formatPlatformCasesCopy(cases) {
  return cases.map((pc, i) => {
    const body = formatPlatformCaseCopy(pc);
    return cases.length > 1 ? `--- 案例 ${i + 1} ---\n${body}` : body;
  }).join('\n');
}

export function treeToMarkdownOutline(tree) {
  const lines = [
    '# 測試案例樹狀圖（平台合併格式）',
    '',
    '> 同一功能頁面/元件多列合併為一案例，含多個測試步驟',
    ''
  ];
  for (const pc of tree.platformCases) {
    lines.push(formatPlatformCaseCopy(pc));
    lines.push('');
  }
  return lines.join('\n');
}

export function treeToMermaidFlowchart(tree) {
  const lines = ['flowchart LR'];
  let n = 0;
  const id = () => `n${n++}`;
  for (const root of tree.roots) {
    for (const pc of collectPlatformCasesFromNavNode(root)) {
      let prev = id();
      lines.push(`  ${prev}["${escapeMermaidLabel(pc.mainModule)}"]`);
      for (const f of pc.folderPath) {
        const cur = id();
        lines.push(`  ${cur}["${escapeMermaidLabel(f)}"]`);
        lines.push(`  ${prev} --> ${cur}`);
        prev = cur;
      }
      const leaf = id();
      lines.push(`  ${leaf}["${escapeMermaidLabel(pc.caseTitle)}"]`);
      lines.push(`  ${prev} --> ${leaf}`);
    }
  }
  return lines.join('\n');
}
