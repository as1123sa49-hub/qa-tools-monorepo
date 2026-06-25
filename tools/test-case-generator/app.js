/**
 * 測試案例自動產生工具 — 前端邏輯
 * 規格書解析（PDF / DOCX / XLSX / CSV）→ AI → JSON 修復 → 表格顯示 → XLSX 匯出
 * 功能：IndexedDB 快取舊版規格 / 附加分析模式
 */

import {
  getTodayStr,
  normalizeMainModule,
  stripFeatureMarkers,
  normalizeTierLevel,
  TIER_SORT,
  PRIO_SORT,
  caseTypeOrder,
} from './js/case-utils.js';
import { enrichFeaturePath, enrichSpecSource, enrichXlsxSpecSource, enrichSpecSourceForMulti, pickWrappedSpecTextForSource } from './js/feature-path.js';
import {
  buildPrdCoverageReport,
  formatPrdCoverageWarning,
  buildModuleCoverageSummary,
  compareCaseSetsByFeature,
  caseMatchesDoc,
  buildXlsxSheetCoverageReport,
  formatXlsxSheetCoverageWarning,
} from './js/coverage.js';
import { mergeSpecOutlines, classifyMultiSpecFeature } from './js/multi-classify.js';
import {
  buildOutlineFromManualRows,
  formatManualIndexForPrompt,
  isValidManualIndexRows,
  loadManualIndexRows,
  saveManualIndexRows,
  splitManualL3Lines,
  DEFAULT_MANUAL_INDEX_ROWS,
} from './js/manual-index.js';
import { fixTruncatedJson, repairJsonControlChars } from './js/json-repair.js';
import {
  LLM_PROVIDER_STORAGE_KEY,
  PROVIDER_GEMINI,
  PROVIDER_SIRAYA,
  getLlmProvider,
  getApiKeyStorageKey,
  getModelsForProvider,
  getDefaultModelForProvider,
  getModelStorageKey,
  getSelectedModelId,
  getProviderLabel,
  getApiKeyLabel,
  renderModelOptions,
  callLlm,
  formatApiError,
  llmSleep,
  MULTI_BATCH_THROTTLE_MS,
} from './js/llm.js';
import {
  extractSpecText,
  extractXlsxSpecText,
  listXlsxSheets,
  getSpecFormat,
  getSpecFileKey,
  isSpecFile,
  suggestSkipSheet,
  formatExtractSummary,
} from './js/spec-extract.js';
import {
  PROMPT_FULL,
  PROMPT_MULTI,
  PROMPT_DIFF,
  PROMPT_BASELINE_DIFF,
  PROMPT_OBSOLETE,
  PROMPT_DUP_CONFIRM,
  PROMPT_MODULAR_CONFIRM,
  PROMPT_REFILL,
} from './js/prompts.js';
import {
  MINDMAP_MAIN_ORDER,
  isMindmapCaseValid,
  buildMindMapTree,
  countPlatformCasesInNavNode,
  countRowsInNavNode,
  collectPlatformCasesFromNavNode,
  findNavNodeByPath,
  formatPlatformCaseCopy,
  formatPlatformCasesCopy,
  treeToMarkdownOutline,
  treeToMermaidFlowchart,
} from './js/mindmap-core.js';

// ─── PDF.js 設定 ────────────────────────────────────────────
pdfjsLib.GlobalWorkerOptions.workerSrc =
  'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';

// ═══════════════════════════════════════════════════════════
// IndexedDB 快取（儲存上次分析的規格書文字）
// ═══════════════════════════════════════════════════════════
const IDB_NAME        = 'testCaseGen';
const IDB_VER         = 2;
const IDB_STORE       = 'specCache';
const IDB_CASES_STORE = 'casesCache';

function openDB() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(IDB_NAME, IDB_VER);
    req.onupgradeneeded = e => {
      const db = e.target.result;
      if (!db.objectStoreNames.contains(IDB_STORE))
        db.createObjectStore(IDB_STORE, { keyPath: 'id' });
      if (!db.objectStoreNames.contains(IDB_CASES_STORE))
        db.createObjectStore(IDB_CASES_STORE, { keyPath: 'id' });
    };
    req.onsuccess = e => resolve(e.target.result);
    req.onerror   = e => reject(e.target.error);
  });
}

async function dbSaveSpec(filename, text) {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(IDB_STORE, 'readwrite');
    tx.objectStore(IDB_STORE).put({
      id: 'lastSpec', filename, text,
      savedAt: new Date().toLocaleString('zh-TW')
    });
    tx.oncomplete = () => resolve();
    tx.onerror    = e => reject(e.target.error);
  });
}

async function dbLoadSpec() {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx  = db.transaction(IDB_STORE, 'readonly');
    const req = tx.objectStore(IDB_STORE).get('lastSpec');
    req.onsuccess = e => resolve(e.target.result || null);
    req.onerror   = e => reject(e.target.error);
  });
}

async function dbClearSpec() {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(IDB_STORE, 'readwrite');
    tx.objectStore(IDB_STORE).delete('lastSpec');
    tx.oncomplete = () => resolve();
    tx.onerror    = e => reject(e.target.error);
  });
}

// ─── IndexedDB 案例快取 ──────────────────────────────────────
async function dbSaveCases(cases) {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(IDB_CASES_STORE, 'readwrite');
    tx.objectStore(IDB_CASES_STORE).put({
      id: 'current', cases,
      savedAt: new Date().toLocaleString('zh-TW'),
      count: cases.length
    });
    tx.oncomplete = () => resolve();
    tx.onerror    = e => reject(e.target.error);
  });
}

async function dbLoadCases() {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx  = db.transaction(IDB_CASES_STORE, 'readonly');
    const req = tx.objectStore(IDB_CASES_STORE).get('current');
    req.onsuccess = e => resolve(e.target.result || null);
    req.onerror   = e => reject(e.target.error);
  });
}

async function dbClearCases() {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(IDB_CASES_STORE, 'readwrite');
    tx.objectStore(IDB_CASES_STORE).delete('current');
    tx.oncomplete = () => resolve();
    tx.onerror    = e => reject(e.target.error);
  });
}

// ─── 快取狀態 ────────────────────────────────────────────────
let cachedSpec = null;  // { filename, text, savedAt }
let useCache   = false; // 是否以快取作為舊版比對
let analysisMode = 'spec'; // spec | multi | modularize | baseline | mindmap

function getSupplementFiles() {
  return Array.from(document.getElementById('supplementFiles')?.files || []);
}

let manualIndexSaveTimer = null;

function collectManualIndexRowsFromUi() {
  const list = document.getElementById('manualIndexList');
  if (!list) return [];
  return [...list.querySelectorAll('.manual-index-card.manual-index-row')].map(card => ({
    l1: card.querySelector('.manual-l1')?.value?.trim() || '',
    l2: card.querySelector('.manual-l2')?.value?.trim() || '',
    l3: card.querySelector('.manual-l3')?.value ?? '',
    note: card.querySelector('.manual-note')?.value?.trim() || '',
    collapsed: card.classList.contains('collapsed'),
  }));
}

function updateManualIndexCardSummary(card) {
  const preview = card.querySelector('.manual-index-l3-preview');
  if (!preview) return;
  const lines = splitManualL3Lines(card.querySelector('.manual-l3')?.value ?? '');
  preview.textContent = lines.length
    ? (lines.length <= 4
      ? lines.join(' · ')
      : `${lines.slice(0, 4).join(' · ')} …共 ${lines.length} 項`)
    : '';
}

function setManualIndexCardCollapsed(card, collapsed) {
  card.classList.toggle('collapsed', collapsed);
  const toggle = card.querySelector('.manual-index-toggle');
  if (toggle) {
    toggle.textContent = collapsed ? '▶' : '▼';
    toggle.setAttribute('aria-expanded', String(!collapsed));
  }
  updateManualIndexCardSummary(card);
}

function scrollManualIndexCardIntoView(card) {
  const scroller = document.getElementById('manualIndexScroll');
  if (!scroller || !card) return;
  const pad = 8;
  const cardRect = card.getBoundingClientRect();
  const scrollerRect = scroller.getBoundingClientRect();
  if (cardRect.bottom > scrollerRect.bottom - pad) {
    scroller.scrollTop += cardRect.bottom - scrollerRect.bottom + pad;
  }
  if (cardRect.top < scrollerRect.top + pad) {
    scroller.scrollTop += cardRect.top - scrollerRect.top - pad;
  }
}

function toggleManualIndexCard(card) {
  const wasCollapsed = card.classList.contains('collapsed');
  setManualIndexCardCollapsed(card, !wasCollapsed);
  if (wasCollapsed) {
    requestAnimationFrame(() => scrollManualIndexCardIntoView(card));
  }
  scheduleSaveManualIndexRows();
}

function scheduleSaveManualIndexRows() {
  clearTimeout(manualIndexSaveTimer);
  manualIndexSaveTimer = setTimeout(() => {
    saveManualIndexRows(collectManualIndexRowsFromUi());
  }, 400);
}

function createManualIndexCard(row = {}) {
  const collapsed = row.collapsed === true;
  const card = document.createElement('div');
  card.className = `manual-index-card manual-index-row${collapsed ? ' collapsed' : ''}`;

  const head = document.createElement('div');
  head.className = 'manual-index-card-head';

  const toggle = document.createElement('button');
  toggle.type = 'button';
  toggle.className = 'manual-index-toggle';
  toggle.title = '展開／收合 L3';
  toggle.textContent = collapsed ? '▶' : '▼';
  toggle.setAttribute('aria-expanded', String(!collapsed));

  const mkField = (label, className, placeholder, value, tag = 'input') => {
    const wrap = document.createElement('div');
    wrap.className = 'manual-index-field';
    const lbl = document.createElement('div');
    lbl.className = 'manual-index-field-label';
    lbl.textContent = label;
    const el = document.createElement(tag);
    el.className = className;
    if (tag === 'input') {
      el.type = 'text';
      el.placeholder = placeholder;
    } else {
      el.placeholder = placeholder;
      el.rows = 4;
    }
    el.value = value || '';
    wrap.append(lbl, el);
    return wrap;
  };

  const fieldL1 = mkField('L1 主模組', 'manual-l1', '例：前端、會員系統', row.l1);
  const fieldL2 = mkField('L2 功能群', 'manual-l2', '[頂部]功能列', row.l2);
  const fieldNote = mkField('說明', 'manual-note', '選填', row.note);

  const btnDel = document.createElement('button');
  btnDel.type = 'button';
  btnDel.className = 'manual-index-del';
  btnDel.title = '刪除此功能群';
  btnDel.textContent = '×';

  head.append(toggle, fieldL1, fieldL2, fieldNote, btnDel);

  const preview = document.createElement('div');
  preview.className = 'manual-index-l3-preview';
  head.appendChild(preview);

  const body = document.createElement('div');
  body.className = 'manual-index-card-body';
  const lblL3 = document.createElement('label');
  lblL3.textContent = 'L3 細項（每行一項）';
  const taL3 = document.createElement('textarea');
  taL3.className = 'manual-l3';
  taL3.placeholder = '邊界\n公司Logo\n分頁選項';
  taL3.value = row.l3 || '';
  body.append(lblL3, taL3);

  card.append(head, body);
  updateManualIndexCardSummary(card);

  toggle.addEventListener('click', (e) => {
    e.stopPropagation();
    toggleManualIndexCard(card);
  });
  head.addEventListener('click', (e) => {
    if (e.target.closest('input, textarea, button.manual-index-del')) return;
    toggleManualIndexCard(card);
  });

  card.querySelectorAll('input, textarea').forEach(el => {
    el.addEventListener('input', () => {
      updateManualIndexCardSummary(card);
      scheduleSaveManualIndexRows();
      checkReady();
    });
    el.addEventListener('click', (e) => e.stopPropagation());
  });
  btnDel.addEventListener('click', (e) => {
    e.stopPropagation();
    const list = document.getElementById('manualIndexList');
    if (list && list.querySelectorAll('.manual-index-card.manual-index-row').length > 1) {
      card.remove();
      scheduleSaveManualIndexRows();
      checkReady();
    }
  });
  return card;
}

function renderManualIndexRows(rows) {
  const list = document.getElementById('manualIndexList');
  if (!list) return;
  list.innerHTML = '';
  const data = rows?.length ? rows : DEFAULT_MANUAL_INDEX_ROWS;
  for (const row of data) {
    list.appendChild(createManualIndexCard(row));
  }
}

function hasManualIndexFile() {
  return document.getElementById('newFile')?.files?.length > 0;
}

function syncManualIndexDisabled() {
  const wrap = document.getElementById('manualIndexWrap');
  if (!wrap) return;
  const disabled = analysisMode === 'multi' && hasManualIndexFile();
  wrap.classList.toggle('disabled', disabled);
}

function initManualIndexPanel() {
  const saved = loadManualIndexRows();
  renderManualIndexRows(saved || DEFAULT_MANUAL_INDEX_ROWS);

  document.getElementById('manualIndexAddRow')?.addEventListener('click', () => {
    const list = document.getElementById('manualIndexList');
    const card = createManualIndexCard({ l1: '', l2: '', l3: '', note: '', collapsed: false });
    list?.appendChild(card);
    requestAnimationFrame(() => scrollManualIndexCardIntoView(card));
    scheduleSaveManualIndexRows();
    checkReady();
  });
}

function formatSupplementLabel(files) {
  if (!files.length) return '';
  if (files.length === 1) return `📎 ${files[0].name}`;
  return `📚 共 ${files.length} 份：${files.map(f => f.name).join('、')}`;
}

function wrapSpecDocument(filename, text) {
  const name = (filename || '').trim();
  const body = (text || '').trim();
  if (!name) return body;
  if (!body) return `【規格書：${name}】`;
  return `【規格書：${name}】\n${body}`;
}

function buildMultiSpecBundle(indexName, indexText, specDocs) {
  const name = (indexName || '模組索引').trim();
  const segments = [
    `【模組索引／分類：${name}】\n${indexText}`
  ];
  if (specDocs.length) {
    segments.push('【功能規格書（本批掃描對象，請完整邏輯窮舉）】');
    for (const doc of specDocs) {
      segments.push(`【規格書：${doc.name}】\n${doc.text}`);
    }
  }
  return segments.join('\n\n');
}

function rebuildMultiOutlines(indexText, specDocs, currentDoc = null, manualOutline = null) {
  lastIndexOutline = manualOutline ?? buildSpecOutline(indexText);
  if (currentDoc) {
    lastContentOutline = buildSpecOutline(currentDoc.text);
  } else if (specDocs?.length) {
    let merged = { mainOrder: [], items: [] };
    for (const d of specDocs) {
      merged = mergeSpecOutlines(merged, buildSpecOutline(d.text));
    }
    lastContentOutline = merged;
  } else {
    lastContentOutline = buildSpecOutline(indexText);
  }
  lastSpecOutline = mergeSpecOutlines(lastIndexOutline, lastContentOutline);
}

function showCacheNotice(spec) {
  cachedSpec = spec;
  document.getElementById('cacheFilename').textContent = spec.filename;
  document.getElementById('cacheSavedAt').textContent  = `儲存於 ${spec.savedAt}`;
  document.getElementById('cacheNotice').classList.add('visible');
}

function hideCacheNotice() {
  document.getElementById('cacheNotice').classList.remove('visible');
  cachedSpec = null;
  deactivateCache();
}

function activateCache() {
  useCache = true;
  document.getElementById('useAsOldBtn').classList.add('active');
  document.getElementById('useAsOldBtn').textContent = '✅ 已選為舊版';
  checkReady();

  const zone = document.getElementById('oldZone');
  zone.classList.add('using-cache');
  document.getElementById('oldZoneLabel').textContent = `使用快取：${cachedSpec.filename}`;
  document.getElementById('oldZoneSub').textContent   = '（來自上次分析）';
  document.getElementById('oldZoneOptional').textContent = '';
  document.getElementById('oldFileName').textContent  = '';
}

function deactivateCache() {
  useCache = false;
  const btn = document.getElementById('useAsOldBtn');
  if (btn) {
    btn.classList.remove('active');
    btn.textContent = '📋 用作舊版比對';
  }
  const zone = document.getElementById('oldZone');
  if (zone) zone.classList.remove('using-cache');
  document.getElementById('oldZoneLabel').textContent    = '拖曳或點擊上傳';
  document.getElementById('oldZoneSub').textContent      = 'PDF / DOCX / XLSX / CSV（差異比對用）';
  document.getElementById('oldZoneOptional').textContent = '⚠ 不上傳則產出完整案例';
  checkReady();
}

async function loadCacheOnStartup() {
  try {
    const spec = await dbLoadSpec();
    if (!spec) return;
    showCacheNotice(spec);
    if (spec.text) {
      lastNewSpecText = spec.text;
      if (spec.filename && !lastSpecSourceFilename) {
        lastSpecSourceFilename = spec.filename.replace(/\s*\+.*$/, '').trim();
      }
    }
  } catch (_) {}
}

// ─── 附加確認 Modal ──────────────────────────────────────────
function promptAppendOrReplace() {
  return new Promise(resolve => {
    document.getElementById('existingCount').textContent = currentCases.length;
    document.getElementById('appendModal').classList.add('visible');

    const appendBtn  = document.getElementById('modalAppendBtn');
    const replaceBtn = document.getElementById('modalReplaceBtn');

    function cleanup(choice) {
      document.getElementById('appendModal').classList.remove('visible');
      appendBtn.onclick  = null;
      replaceBtn.onclick = null;
      resolve(choice);
    }

    appendBtn.onclick  = () => cleanup('append');
    replaceBtn.onclick = () => cleanup('replace');
  });
}

// ─── 階層：主模組 / 層級(L1-L3) / 功能頁面/元件 ─────────────────



/** 功能名稱與 outline 節點是否對應（允許部分包含） */
function featureMatchesItem(feat, itemName) {
  const f = stripFeatureMarkers(feat).toLowerCase();
  const n = stripFeatureMarkers(itemName).toLowerCase();
  if (!f || !n) return false;
  if (f === n) return true;
  if (f.includes(n) || n.includes(f)) {
    return Math.min(f.length, n.length) / Math.max(f.length, n.length) > 0.55;
  }
  return false;
}

/** 依規格 ◆ outline 推斷 L2 / L3（優先於 AI 預設 L3） */
function inferTierFromOutline(mainMod, feat, outline) {
  const main = normalizeMainModule(mainMod || '');
  const f = stripFeatureMarkers(feat || '');
  if (!f) return 'L2';

  const items = (outline?.items || []).filter(it => normalizeMainModule(it.main) === main);
  const l2Items = items.filter(it => it.tier === 'L2');
  const l3Items = items.filter(it => it.tier === 'L3');

  if (l3Items.some(it => featureMatchesItem(f, it.name))) return 'L3';

  for (const it of l2Items) {
    const n = stripFeatureMarkers(it.name);
    if (f === n) return 'L2';
    if (featureMatchesItem(f, n) && Math.abs(f.length - n.length) <= 10) return 'L2';
  }

  for (const it of l2Items) {
    if (featureMatchesItem(f, it.name)) return 'L2';
  }

  if (l3Items.length > 0) {
    for (const l2 of l2Items) {
      const l2n = stripFeatureMarkers(l2.name);
      const children = l3Items.filter(c => c.l2 === l2n || c.l2 === l2.l2);
      if (children.length && !featureMatchesItem(f, l2n)) {
        if (children.some(c => featureMatchesItem(f, c.name))) return 'L3';
        return 'L3';
      }
    }
  }

  if (
    l2Items.length > 0 &&
    /內容規格|說明頁|FAQ|條款|政策|控制規格|切換規格|模式設定|元件規格/.test(f) &&
    !l2Items.some(it => f === stripFeatureMarkers(it.name))
  ) {
    return 'L3';
  }

  return 'L2';
}

function resolveCaseTier(entry, mainMod, feat, outline) {
  const aiTier = normalizeTierLevel(entry['層級']);
  const inferred = inferTierFromOutline(mainMod, feat, outline);
  if (aiTier === 'L1') return 'L1';
  if (inferred === 'L2') return 'L2';
  if (inferred === 'L3') return 'L3';
  return aiTier || inferred;
}

function buildSpecOutline(specText) {
  const mainOrder = [];
  const items = [];
  let order = 0;
  let currentMain = null;

  const isMainTitle = (title) =>
    /^(通用功能|玩家系統|會員系統|金流系統|KYC|遊戲大廳)/.test(title);

  const pushItem = (title, tierHint) => {
    if (!title) return;
    if (isMainTitle(title)) {
      currentMain = title.startsWith('通用功能') ? '通用功能' : normalizeMainModule(title);
      if (!mainOrder.includes(currentMain)) mainOrder.push(currentMain);
      items.push({ main: currentMain, tier: 'L1', name: title, l2: null, order: order++ });
    } else if (currentMain) {
      items.push({ main: currentMain, tier: tierHint || 'L2', name: title, l2: title, order: order++ });
    } else {
      currentMain = '通用功能';
      if (!mainOrder.includes('通用功能')) mainOrder.push('通用功能');
      items.push({ main: currentMain, tier: tierHint || 'L2', name: title, l2: title, order: order++ });
    }
  };

  const extractOutlineTitle = (line) => {
    const trimmed = line.trim();
    let m = trimmed.match(/◆\s*(.+?)(?:\s*\(|：|:|$)/);
    if (m) return m[1].trim();
    m = trimmed.match(/^(?:\d+\.){1,4}\d*\s+(.+?)(?:\s*[（(]|$)/);
    if (m && m[1].length <= 40) return m[1].trim();
    m = trimmed.match(/^第[一二三四五六七八九十百千\d]+[章节節][：:\s]+(.+?)(?:\s*[（(]|$)/);
    if (m && m[1].length <= 40) return m[1].trim();
    return null;
  };

  for (const line of (specText || '').split(/\r?\n/)) {
    const title = extractOutlineTitle(line);
    if (!title) continue;
    const tierHint = /分面|子功能|細項|元件/.test(title) ? 'L3' : 'L2';
    pushItem(title, tierHint);
  }
  return { mainOrder, items };
}


function matchItemOrder(outline, c) {
  const main = normalizeMainModule(c['主模組'] || '');
  const feat = stripFeatureMarkers(c['功能頁面/元件'] || '');
  let best = 99999;
  for (const it of outline.items || []) {
    if (it.main !== main) continue;
    if (feat && featureMatchesItem(feat, it.name) && it.order < best) best = it.order;
  }
  return best;
}

function sortCasesByOutline(cases, outline) {
  const out = outline && outline.mainOrder ? outline : { mainOrder: [], items: [] };
  return [...cases].sort((a, b) => {
    const ma = normalizeMainModule(a['主模組'] || '');
    const mb = normalizeMainModule(b['主模組'] || '');
    let ia = out.mainOrder.indexOf(ma);
    let ib = out.mainOrder.indexOf(mb);
    if (ia < 0) ia = 999;
    if (ib < 0) ib = 999;
    if (ia !== ib) return ia - ib;

    const oa = matchItemOrder(out, a);
    const ob = matchItemOrder(out, b);
    if (oa !== ob) return oa - ob;

    const ta = TIER_SORT[(a['層級'] || '').toUpperCase()] ?? 9;
    const tb = TIER_SORT[(b['層級'] || '').toUpperCase()] ?? 9;
    if (ta !== tb) return ta - tb;

    const fc = stripFeatureMarkers(a['功能頁面/元件'] || '')
      .localeCompare(stripFeatureMarkers(b['功能頁面/元件'] || ''), 'zh-TW', { numeric: true });
    if (fc !== 0) return fc;

    const tya = caseTypeOrder(a['測試類型']);
    const tyb = caseTypeOrder(b['測試類型']);
    if (tya !== tyb) return tya - tyb;

    return (PRIO_SORT[a['優先度']] ?? 9) - (PRIO_SORT[b['優先度']] ?? 9);
  });
}

function normalizeCaseEntry(entry, outline, opts = {}) {
  const rawPrio = entry['優先度'] || entry['影響層級'] || entry['priority'] || '';
  const priority = rawPrio.replace(/\s*[\(（][^)）]*[\)）]/g, '').trim();

  const featRawIn = (entry['功能頁面/元件'] || entry['功能模組'] || entry['模組'] || entry['功能'] || '').trim();
  let mainMod = normalizeMainModule(entry['主模組'] || '');
  if (!mainMod && /大廳|遊戲列表|遊戲入口/.test(featRawIn)) mainMod = '遊戲大廳';

  const indexO = opts.indexOutline ?? lastIndexOutline;
  const contentO = opts.contentOutline ?? lastContentOutline;
  const o = outline || lastSpecOutline;
  const tierOutline = indexO?.items?.length ? indexO : o;
  const tier = resolveCaseTier(entry, mainMod, featRawIn, tierOutline);

  const rawSrcIn = entry['規格來源'] || entry['來源'] || entry['spec_source'] || '';
  const specFilename = opts.specFilename ?? lastSpecSourceFilename;
  let rawSrc = rawSrcIn;
  if (specFilename && (opts.enrichSpecSource || analysisMode === 'spec' || opts.multiClassify)) {
    rawSrc = enrichSpecSource(rawSrcIn, specFilename);
  } else if (opts.multiClassify && opts.supplementDocs?.length) {
    rawSrc = enrichSpecSourceForMulti(
      rawSrcIn,
      opts.supplementDocs.map(d => d.name)
    );
  }
  let specText = opts.specText;
  if (!specText && opts.multiClassify && opts.supplementDocs?.length) {
    specText = pickWrappedSpecTextForSource(rawSrc, opts.supplementDocs);
  }
  if (!specText) specText = lastNewSpecText;
  if (specText) {
    rawSrc = enrichXlsxSpecSource(rawSrc, specText);
  }

  let feat = featRawIn;
  if (opts.multiClassify || analysisMode === 'multi') {
    const classified = classifyMultiSpecFeature(
      featRawIn, entry, indexO, contentO, mainMod, tier
    );
    mainMod = classified.mainMod || mainMod;
    feat = classified.feat || featRawIn;
  } else {
    feat = enrichFeaturePath(featRawIn, { mainMod, rawSrc, outline: o, tier });
  }

  const srcSuspicious = rawSrc.trim() !== '' && /^\d+\.[a-zA-Z]$/.test(rawSrc.trim());

  return {
    '狀態': entry['狀態'] || '',
    '取代者': entry['取代者'] || '',
    '測試類型': entry['測試類型'] || '',
    '類別': entry['類別'] || '',
    '前置條件': entry['前置條件'] || '',
    '優先度': priority,
    '主模組': mainMod,
    '層級': tier,
    '功能頁面/元件': feat,
    '規格來源': rawSrc,
    '_srcSuspicious': srcSuspicious,
    '測試標題': entry['測試標題'] || entry['標題'] || entry['title'] || '',
    '預期結果': entry['預期結果'] || entry['結果'] || entry['expected'] || '',
    '編號': entry['編號'] || entry['id'] || entry['case_id'] || '',
    '版本標籤': entry['版本標籤'] || entry['版本'] || entry['version'] || ''
  };
}


// ─── 失效案例驗證（Step V）────────────────────────────────────
async function runObsoleteCheck(apiKey, newText, existingCases, newCases) {
  const toSummary = arr => arr.map(c => ({
    編號: c['編號'],
    主模組: c['主模組'],
    層級: c['層級'],
    '功能頁面/元件': c['功能頁面/元件'],
    測試標題: c['測試標題'],
    預期結果: c['預期結果']
  }));
  const summary    = toSummary(existingCases);
  const newSummary = toSummary(newCases);

  const stepVEl     = document.getElementById('stepV');
  const stepVIcon   = document.getElementById('stepVIcon');
  const stepVText   = document.getElementById('stepVText');
  const pWrap       = document.getElementById('stepVProgressWrap');
  const pFill       = document.getElementById('stepVProgressFill');
  const pPct        = document.getElementById('stepVProgressPct');
  const pSec        = document.getElementById('stepVProgressSec');

  stepVEl.style.display  = '';
  stepVIcon.className    = 'step-icon running';
  stepVIcon.textContent  = '🔍';
  stepVText.className    = 'step-text active';
  stepVText.textContent  = `驗證 ${existingCases.length} 筆舊案例是否符合新規格...`;
  pWrap.style.display    = 'flex';

  let fakeP = 0, elapsed = 0;
  const timer = setInterval(() => {
    elapsed++;
    const spd = fakeP < 50 ? 3 : fakeP < 75 ? 1.5 : 0.5;
    fakeP = Math.min(fakeP + spd * (Math.random() * 0.8 + 0.6), 92);
    pFill.style.width = fakeP + '%';
    pPct.textContent  = Math.floor(fakeP) + '%';
    pSec.textContent  = `已等待 ${elapsed} 秒`;
  }, 1000);

  // [{ id, replacedBy }]
  let obsoleteList = [];
  try {
    const raw = await callLlm(getLlmProvider(), apiKey,
      PROMPT_OBSOLETE(newText, JSON.stringify(summary, null, 2), JSON.stringify(newSummary, null, 2)),
      getSelectedModelId()
    );
    const cleaned = raw.replace(/```json|```/g, '').trim();
    const parsed  = JSON.parse(cleaned);
    if (Array.isArray(parsed)) {
      obsoleteList = parsed
        .filter(o => o && typeof o['編號'] === 'string')
        .map(o => ({
          id: o['編號'],
          replacedBy: (o['取代者'] && o['取代者'] !== o['編號']) ? o['取代者'] : null
        }));
    }
  } catch (_) {
    // 驗證失敗不中斷主流程，忽略錯誤
  } finally {
    clearInterval(timer);
    pFill.style.width  = '100%';
    pPct.textContent   = '100%';
    await new Promise(r => setTimeout(r, 300));
    pWrap.style.display = 'none';
    stepVIcon.className   = 'step-icon done';
    stepVIcon.textContent = '✓';
    stepVText.className   = 'step-text muted';
    stepVText.textContent = obsoleteList.length > 0
      ? `驗證完成（共耗時 ${elapsed} 秒）— 發現 ${obsoleteList.length} 筆失效案例`
      : `驗證完成（共耗時 ${elapsed} 秒）— 所有舊案例均符合新規格`;
  }
  return obsoleteList;
}

// ─── 修復截斷 JSON（來自 n8n Code 節點）────────────────────

let lastAiParseWarning = null;
let lastMultiPrdCoverageWarning = null;
let lastXlsxSheetCoverageWarning = null;
let lastCoverageDocNames = [];
let lastXlsxSheetNames = [];
let coverageInspectCases = null;
let coverageBaselineCases = null;

function showParseWarning(msg) {
  const warn = document.getElementById('emptyWarn');
  if (!warn || !msg) return;
  warn.style.display = 'inline';
  warn.style.color = 'var(--yellow)';
  warn.style.fontWeight = '600';
  warn.style.cursor = 'default';
  warn.textContent = msg;
  warn.onclick = null;
}

function showResultWarnings() {
  const msgs = [
    lastAiParseWarning,
    lastMultiPrdCoverageWarning,
    lastXlsxSheetCoverageWarning,
  ].filter(Boolean);
  if (msgs.length) showParseWarning(msgs.join(' '));
}

function formatTruncationWarning(parsedLength, context) {
  if (context?.type === 'sheet' && context.name) {
    return `⚠ 工作表「${context.name}」AI 回傳可能已截斷（僅保留 ${parsedLength} 筆）。請重試該工作表批次。`;
  }
  if (context?.type === 'full-xlsx') {
    return `⚠ AI 回傳可能已截斷（僅保留 ${parsedLength} 筆）。若規格為多分頁 XLSX，請勾選 2 個以上工作表以自動分批分析。`;
  }
  return `⚠ AI 回傳可能已截斷（僅保留 ${parsedLength} 筆）。建議分批上傳補充 PRD 後用附加模式合併。`;
}

function applySpecFullCoverage(newFile, cases, selectedSheets) {
  if (!newFile?.name) return;
  setCoverageDocNames([newFile.name]);
  coverageInspectCases = null;
  if (getSpecFormat(newFile) === 'xlsx' && selectedSheets?.length) {
    lastXlsxSheetNames = [...selectedSheets];
    lastXlsxSheetCoverageWarning = formatXlsxSheetCoverageWarning(
      buildXlsxSheetCoverageReport(newFile.name, selectedSheets, cases)
    );
  } else {
    lastXlsxSheetNames = [];
    lastXlsxSheetCoverageWarning = null;
  }
}

/** 檢查產出案例的規格來源是否涵蓋每份補充 PRD */
function checkMultiPrdCoverage(supplementDocs, cases) {
  const names = (supplementDocs || []).map(d => d.name).filter(Boolean);
  if (!names.length || !cases?.length) return null;
  return formatPrdCoverageWarning(buildPrdCoverageReport(names, cases));
}

function getCoverageCases() {
  return coverageInspectCases?.length ? coverageInspectCases : currentCases;
}

function getCoverageDocNamesFromUi() {
  const ta = document.getElementById('coveragePrdList');
  const fromUi = (ta?.value || '')
    .split(/\r?\n/)
    .map(s => s.trim())
    .filter(Boolean);
  if (fromUi.length) return fromUi;
  return lastCoverageDocNames;
}

function syncCoveragePrdListFromUploads() {
  const files = getSupplementFiles();
  if (!files.length) return false;
  const names = files.map(f => f.name);
  lastCoverageDocNames = names;
  const ta = document.getElementById('coveragePrdList');
  if (ta) ta.value = names.join('\n');
  return true;
}

function setCoverageDocNames(names) {
  lastCoverageDocNames = [...new Set((names || []).map(n => n.trim()).filter(Boolean))];
  const ta = document.getElementById('coveragePrdList');
  if (ta && lastCoverageDocNames.length) ta.value = lastCoverageDocNames.join('\n');
}

function renderCoverageReportHtml(report, moduleSummary, baselineCompare, sheetReport) {
  const covered = report.prdWithCases;
  const total = report.prdTotal;
  let html = `<div class="coverage-summary">`;
  html += `案例 <strong>${report.totalCases}</strong> 筆`;
  if (total) {
    html += ` · PRD 覆蓋 <strong>${covered}/${total}</strong> 份`;
  }
  if (sheetReport?.sheetTotal) {
    html += ` · 工作表覆蓋 <strong>${sheetReport.sheetWithCases}/${sheetReport.sheetTotal}</strong> 個`;
  }
  if (report.unmatchedToPrd > 0) {
    html += ` · <span class="cov-badge-warn">${report.unmatchedToPrd} 筆未對應任何 PRD 檔名</span>`;
  }
  html += `</div>`;

  if (report.items.length) {
    html += `<table class="coverage-table"><thead><tr><th>功能規格書</th><th>案例數</th><th>狀態</th></tr></thead><tbody>`;
    for (const item of report.items) {
      const statusCls = !item.covered ? 'cov-badge-miss' : item.count === 0 ? 'cov-badge-miss' : 'cov-badge-ok';
      const statusText = !item.covered ? '未覆蓋' : `${item.count} 筆`;
      html += `<tr class="cov-row" data-coverage-prd="${escapeHtml(item.name)}">`;
      html += `<td>${escapeHtml(item.name)}</td>`;
      html += `<td>${item.count}</td>`;
      html += `<td class="${statusCls}">${statusText}</td></tr>`;
    }
    html += `</tbody></table>`;
  }

  if (sheetReport?.items?.length) {
    html += `<table class="coverage-table"><thead><tr><th>工作表</th><th>案例數</th><th>狀態</th></tr></thead><tbody>`;
    for (const item of sheetReport.items) {
      const statusCls = !item.covered ? 'cov-badge-miss' : 'cov-badge-ok';
      const statusText = !item.covered ? '未覆蓋' : `${item.count} 筆`;
      html += `<tr><td>${escapeHtml(item.name)}</td>`;
      html += `<td>${item.count}</td>`;
      html += `<td class="${statusCls}">${statusText}</td></tr>`;
    }
    html += `</tbody></table>`;
  }

  if (moduleSummary?.length) {
    html += `<div class="coverage-modules">模組分布：`;
    html += moduleSummary.map(m =>
      `<span>${escapeHtml(m.key)} <strong>${m.count}</strong></span>`
    ).join(' · ');
    html += `</div>`;
  }

  if (baselineCompare?.baselineTotal) {
    const d = baselineCompare.deltaTotal;
    const sign = d > 0 ? '+' : '';
    html += `<div class="coverage-baseline">`;
    html += `基準比對：<strong>${baselineCompare.currentTotal}</strong> / ${baselineCompare.baselineTotal} 筆（${sign}${d}）`;
    if (baselineCompare.gaps.length) {
      html += `<div class="coverage-gap-list">`;
      const top = baselineCompare.gaps.slice(0, 12);
      for (const g of top) {
        const [main, feat] = g.key.split('::');
        const label = feat ? `${main} / ${feat}` : main || g.key;
        html += `<div>${escapeHtml(label)}：基準 ${g.baseline} → 目前 ${g.current}（${g.delta}）</div>`;
      }
      if (baselineCompare.gaps.length > 12) {
        html += `<div>…另有 ${baselineCompare.gaps.length - 12} 個功能群缺口</div>`;
      }
      html += `</div>`;
    } else {
      html += ` <span class="cov-badge-ok">各功能群皆達基準數量</span>`;
    }
    html += `</div>`;
  }

  return html;
}

function bindCoverageTableClicks() {
  document.querySelectorAll('#coverageReport tr[data-coverage-prd]').forEach(row => {
    row.addEventListener('click', () => {
      const name = row.getAttribute('data-coverage-prd') || '';
      if (filterPrdDoc === name) {
        filterPrdDoc = null;
      } else {
        filterPrdDoc = name;
        const filter = document.getElementById('filterText');
        if (filter) filter.value = '';
      }
      refreshDisplay();
    });
  });
}

function updateCoveragePanel() {
  const panel = document.getElementById('coveragePanel');
  const reportEl = document.getElementById('coverageReport');
  if (!panel || !reportEl) return;

  const cases = getCoverageCases();
  const docNames = getCoverageDocNamesFromUi();

  if (!cases.length) {
    panel.classList.remove('visible');
    reportEl.innerHTML = '';
    return;
  }

  panel.classList.add('visible');

  if (!docNames.length) {
    reportEl.innerHTML = '<div class="coverage-summary">請在上方填入功能規格書檔名（每行一個），或按「帶入上傳清單」。</div>';
    document.getElementById('coverageClearBaselineBtn')?.style.setProperty(
      'display', coverageBaselineCases?.length ? '' : 'none'
    );
    return;
  }

  const report = buildPrdCoverageReport(docNames, cases);
  const modules = buildModuleCoverageSummary(cases);
  const baselineCompare = coverageBaselineCases?.length
    ? compareCaseSetsByFeature(coverageBaselineCases, cases)
    : null;
  const sheetReport = lastXlsxSheetNames.length && docNames.length === 1
    ? buildXlsxSheetCoverageReport(docNames[0], lastXlsxSheetNames, cases)
    : null;

  reportEl.innerHTML = renderCoverageReportHtml(report, modules, baselineCompare, sheetReport);
  bindCoverageTableClicks();

  lastMultiPrdCoverageWarning = formatPrdCoverageWarning(report);
  if (sheetReport) {
    lastXlsxSheetCoverageWarning = formatXlsxSheetCoverageWarning(sheetReport);
  }

  const clearBaselineBtn = document.getElementById('coverageClearBaselineBtn');
  if (clearBaselineBtn) {
    clearBaselineBtn.style.display = coverageBaselineCases?.length ? '' : 'none';
  }
}

function initCoveragePanel() {
  document.getElementById('coverageCalcBtn')?.addEventListener('click', () => {
    updateCoveragePanel();
    showResultWarnings();
  });

  document.getElementById('coverageSyncPrdBtn')?.addEventListener('click', () => {
    if (!syncCoveragePrdListFromUploads()) {
      showError('多規格上傳區尚無功能規格書，請先選擇檔案');
      return;
    }
    updateCoveragePanel();
    showResultWarnings();
  });

  document.getElementById('coverageImportCasesBtn')?.addEventListener('click', () => {
    document.getElementById('coverageCasesFile')?.click();
  });

  document.getElementById('coverageCasesFile')?.addEventListener('change', async e => {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;
    try {
      const rows = await loadBaselineCasesFromFile(file);
      currentCases = rows.map(r => normalizeCaseEntry(r, lastSpecOutline));
      coverageInspectCases = null;
      document.getElementById('resultSection')?.classList.add('visible');
      if (analysisMode === 'mindmap' && currentCases.length) syncMindmapExportFromCases();
      refreshDisplay();
    } catch (err) {
      showError(err.message || String(err));
    }
  });

  document.getElementById('coverageBaselineBtn')?.addEventListener('click', () => {
    document.getElementById('coverageBaselineFile')?.click();
  });

  document.getElementById('coverageBaselineFile')?.addEventListener('change', async e => {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;
    try {
      const rows = await loadBaselineCasesFromFile(file);
      coverageBaselineCases = rows.map(r => normalizeCaseEntry(r, lastSpecOutline));
      updateCoveragePanel();
      showResultWarnings();
    } catch (err) {
      showError(err.message || String(err));
    }
  });

  document.getElementById('coverageClearBaselineBtn')?.addEventListener('click', () => {
    coverageBaselineCases = null;
    updateCoveragePanel();
    showResultWarnings();
  });
}

// ─── 多規格自動分批 ──────────────────────────────────────────
let lastMultiBatchState = null; // { mainFile, mainText, supplementDocs, failedIndices }
let lastXlsxSheetBatchState = null; // { file, selectedSheets, fullText, failedIndices }
let selectedCaseIds = new Set();
let analysisInProgress = false;

function setExportEnabled(enabled) {
  const btn = document.getElementById('exportCsvBtn');
  if (btn) btn.disabled = !enabled;
}

function derivePrdPrefix(filename, index) {
  const lower = (filename || '').toLowerCase();
  if (lower.includes('turnover')) return 'TUR';
  if (lower.includes('master')) return 'MST';
  if (lower.includes('存提款') || lower.includes('紀錄中心') || lower.includes('存款')) return 'DEP';
  if (lower.includes('提款')) return 'WDR';
  const alnum = filename.match(/[A-Za-z]{3,}/);
  if (alnum) return alnum[0].slice(0, 3).toUpperCase();
  return `P${index + 1}`;
}

function buildExistingRulesSummary(cases, maxItems = 120) {
  const seen = new Set();
  const lines = [];
  for (const c of cases) {
    const feat = stripFeatureMarkers(c['功能頁面/元件'] || '') || '未分類';
    const rule = extractRuleFamilyKey(c);
    const key = `${feat}::${rule}`;
    if (seen.has(key)) continue;
    seen.add(key);
    lines.push(`- ${feat} → ${rule}`);
    if (lines.length >= maxItems) {
      lines.push(`- …（其餘已產規則請勿重複相同功能+規則族）`);
      break;
    }
  }
  return lines.length ? lines.join('\n') : '（尚無）';
}

function sortCasesByFeature(cases) {
  return [...cases].sort((a, b) => {
    const ma = normalizeMainModule(a['主模組'] || '');
    const mb = normalizeMainModule(b['主模組'] || '');
    const ia = MINDMAP_MAIN_ORDER.indexOf(ma);
    const ib = MINDMAP_MAIN_ORDER.indexOf(mb);
    if (ia !== ib) return (ia < 0 ? 999 : ia) - (ib < 0 ? 999 : ib);
    const fa = stripFeatureMarkers(a['功能頁面/元件'] || '');
    const fb = stripFeatureMarkers(b['功能頁面/元件'] || '');
    const fc = fa.localeCompare(fb, 'zh-TW', { numeric: true });
    if (fc !== 0) return fc;
    return (a['編號'] || '').localeCompare(b['編號'] || '', 'zh-TW', { numeric: true });
  });
}

function getDuplicateCases(cases) {
  return [...cases]
    .filter(c => c._dupSuspect && c._dupGroup)
    .sort((a, b) => {
      const gc = (a._dupGroup || '').localeCompare(b._dupGroup || '', undefined, { numeric: true });
      if (gc !== 0) return gc;
      return (a['編號'] || '').localeCompare(b['編號'] || '', 'zh-TW', { numeric: true });
    });
}

function hasDuplicateSuspects(cases = currentCases) {
  return cases.some(c => c._dupSuspect && c._dupGroup);
}

function resolveIdCollisions(newCases, existingIds, prefix) {
  const used = new Set(existingIds.filter(Boolean));
  return newCases.map(c => {
    let id = (c['編號'] || '').trim();
    if (!id) id = `${prefix}_CASE_001`;
    let candidate = id.startsWith(`${prefix}_`) ? id : `${prefix}_${id}`;
    let finalId = candidate;
    let n = 1;
    while (used.has(finalId)) {
      finalId = `${candidate}_${String(n++).padStart(2, '0')}`;
    }
    used.add(finalId);
    return { ...c, '編號': finalId };
  });
}

function markDuplicateSuspects(cases) {
  const byFeatRule = new Map();
  cases.forEach((c, idx) => {
    const feat = stripFeatureMarkers(c['功能頁面/元件'] || '').toLowerCase();
    const rule = extractRuleFamilyKey(c);
    const key = `${feat}::${rule}`;
    if (!byFeatRule.has(key)) byFeatRule.set(key, []);
    byFeatRule.get(key).push(idx);
  });
  const result = cases.map(c => {
    const next = { ...c };
    delete next._dupSuspect;
    delete next._dupGroup;
    return next;
  });
  let groupSeq = 1;
  byFeatRule.forEach((indices) => {
    if (indices.length < 2) return;
    const gid = `DUP-${String(groupSeq++).padStart(3, '0')}`;
    indices.forEach(i => {
      result[i]._dupSuspect = true;
      result[i]._dupGroup = gid;
    });
  });
  return result;
}


async function confirmDuplicateSuspectsWithAi(apiKey, cases) {
  const groups = new Map();
  cases.filter(c => c._dupSuspect && c._dupGroup).forEach(c => {
    if (!groups.has(c._dupGroup)) groups.set(c._dupGroup, []);
    groups.get(c._dupGroup).push(c);
  });
  const payload = [...groups.entries()]
    .filter(([, members]) => members.length >= 2)
    .map(([gid, members]) => ({
      groupId: gid,
      cases: members.map(c => ({
        編號: c['編號'],
        功能頁面: c['功能頁面/元件'],
        測試標題: c['測試標題'],
        預期結果: c['預期結果']
      }))
    }));
  if (!payload.length) return cases;

  const raw = await callLlm(getLlmProvider(), apiKey, PROMPT_DUP_CONFIRM(JSON.stringify(payload, null, 2)), getSelectedModelId());
  let parsed;
  try {
    const cleaned = repairJsonControlChars(raw.replace(/```json|```/g, '').trim());
    parsed = JSON.parse(cleaned);
  } catch (_) {
    return cases;
  }
  if (!Array.isArray(parsed)) return cases;

  const notDup = new Set(
    parsed.filter(r => r && r.groupId && r.isDuplicate === false).map(r => r.groupId)
  );
  return cases.map(c => {
    if (c._dupGroup && notDup.has(c._dupGroup)) {
      const { _dupSuspect, _dupGroup, ...rest } = c;
      return rest;
    }
    return c;
  });
}

function showBatchRetryBar(failedItems, kind = 'prd') {
  const bar = document.getElementById('batchRetryBar');
  const text = document.getElementById('batchRetryText');
  if (!bar || !failedItems?.length) {
    bar?.classList.remove('visible');
    return;
  }
  const label = kind === 'sheet' ? '工作表' : 'PRD';
  text.textContent = `⚠ ${failedItems.length} 個${label}批次失敗：${failedItems.map(d => d.name).join('、')}`;
  bar.classList.add('visible');
}

function hideBatchRetryBar() {
  document.getElementById('batchRetryBar')?.classList.remove('visible');
}

async function runLlmWithProgress(apiKey, prompt, batchLabel) {
  const progressWrap = document.getElementById('aiProgressWrap');
  const progressFill = document.getElementById('aiProgressFill');
  const progressPct = document.getElementById('aiProgressPct');
  const progressSec = document.getElementById('aiProgressSec');
  progressWrap.style.display = 'flex';
  let fakeProgress = 0;
  let elapsedSec = 0;
  if (batchLabel) {
    document.getElementById('step2Text').textContent = batchLabel;
  }
  const progressTimer = setInterval(() => {
    elapsedSec++;
    const speed = fakeProgress < 50 ? 2.5 : fakeProgress < 75 ? 1.2 : 0.4;
    fakeProgress = Math.min(fakeProgress + speed * (Math.random() * 0.8 + 0.6), 92);
    progressFill.style.width = fakeProgress + '%';
    progressPct.textContent = Math.floor(fakeProgress) + '%';
    progressSec.textContent = `已等待 ${elapsedSec} 秒`;
  }, 1000);
  try {
    return await callLlm(getLlmProvider(), apiKey, prompt, getSelectedModelId());
  } finally {
    clearInterval(progressTimer);
    progressFill.style.width = '100%';
    progressPct.textContent = '100%';
    await new Promise(r => setTimeout(r, 200));
    progressWrap.style.display = 'none';
  }
}

async function fetchBatchCases(apiKey, prompt, batchName, truncateContext) {
  let lastErr = null;
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      const rawText = await runLlmWithProgress(
        apiKey,
        prompt,
        attempt > 0 ? `${batchName}（重試中）` : batchName
      );
      const { parsed, truncated } = parseLlmJsonArray(rawText);
      if (truncated) {
        lastAiParseWarning = formatTruncationWarning(parsed.length, truncateContext);
      }
      const rawCases = parsed.map(c => ({
        ...c,
        '狀態': c['狀態'] || '有效',
        '取代者': c['取代者'] || ''
      }));
      if (rawCases.length > 0 || attempt === 1) return { cases: rawCases, warning: lastAiParseWarning };
      lastErr = new Error('本批未產出任何案例');
    } catch (err) {
      lastErr = err;
    }
  }
  throw lastErr || new Error('批次分析失敗');
}

function buildMultiBatchPrompt({ specText, currentPrd, supplementList, existingRules, indexName }) {
  const tpl = document.getElementById('promptMultiTA')?.value || getDefaultMultiTemplate();
  return tpl
    .replace(/\{\{SPEC\}\}/g, specText)
    .replace(/\{\{INDEX_NAME\}\}/g, indexName || '—')
    .replace(/\{\{CURRENT_PRD\}\}/g, currentPrd || '—')
    .replace(/\{\{SUPPLEMENT_LIST\}\}/g, supplementList || '—')
    .replace(/\{\{EXISTING_RULES\}\}/g, existingRules || '（尚無）');
}

function buildMultiSinglePrompt(specText, specDocNames, indexName) {
  const list = (specDocNames || []).map((n, i) => `${i + 1}. ${n}`).join('\n');
  return buildMultiBatchPrompt({
    specText,
    indexName,
    currentPrd: specDocNames?.length === 1
      ? specDocNames[0]
      : `全部 ${specDocNames.length} 份功能規格書`,
    supplementList: list || '—',
    existingRules: '（尚無，請完整掃描每一份功能規格書）'
  });
}

async function processMultiBatchCases(rawCases, prefix, existingIds, batchOpts = {}) {
  const normOpts = {
    multiClassify: true,
    specFilename: batchOpts.specFilename,
    specText: batchOpts.specText,
    supplementDocs: batchOpts.supplementDocs,
  };
  let normalized = rawCases.map(c => normalizeCaseEntry(c, lastSpecOutline, normOpts));
  normalized = resolveIdCollisions(normalized, existingIds, prefix);
  return sortCasesByFeature(normalized);
}

function processXlsxSheetBatchCases(rawCases, prefix, existingIds, batchOpts = {}) {
  const normOpts = {
    specFilename: batchOpts.specFilename,
    specText: batchOpts.specText,
    enrichSpecSource: true,
  };
  let normalized = rawCases.map(c => normalizeCaseEntry(c, lastSpecOutline, normOpts));
  normalized = resolveIdCollisions(normalized, existingIds, prefix);
  return sortCasesByFeature(normalized);
}

function deriveSheetPrefix(sheetName, index) {
  const alnum = (sheetName || '').match(/[A-Za-z]{2,}/);
  if (alnum) return alnum[0].slice(0, 3).toUpperCase();
  const cjk = (sheetName || '').replace(/\s+/g, '').slice(0, 2);
  if (cjk) return `S${index + 1}`;
  return `S${index + 1}`;
}

async function finishXlsxSheetAnalysis({
  apiKey, newFile, newText, selectedSheets, appendMode, specTextForPrompt
}) {
  analysisInProgress = true;
  setExportEnabled(false);
  hideBatchRetryBar();
  lastAiParseWarning = null;
  lastXlsxSheetCoverageWarning = null;
  lastXlsxSheetBatchState = {
    file: newFile,
    selectedSheets: [...selectedSheets],
    fullText: newText,
    failedIndices: [],
  };
  lastXlsxSheetNames = [...selectedSheets];

  if (!appendMode) {
    currentCases = [];
    clearResultFilters();
  }

  setStep(2, 'running');
  const failedSheets = [];
  const total = selectedSheets.length;

  try {
    for (let i = 0; i < total; i++) {
      const sheetName = selectedSheets[i];
      const batchLabel = `工作表 ${i + 1}/${total}：${sheetName}`;
      if (i > 0) await throttleBetweenBatches(`全量產出（${batchLabel}）`);
      document.getElementById('step2Text').textContent = `全量產出（${batchLabel}，分析中…）`;

      const { text: sheetText } = await extractXlsxSpecText(newFile, [sheetName]);
      const wrapped = wrapSpecDocument(newFile.name, sheetText);
      const prompt = buildFullPrompt(wrapped);
      const truncateContext = { type: 'sheet', name: sheetName };

      try {
        const { cases: rawCases, warning } = await fetchBatchCases(
          apiKey,
          prompt,
          `全量產出（${batchLabel}）`,
          truncateContext
        );
        if (warning && !lastAiParseWarning) lastAiParseWarning = warning;
        if (!rawCases.length) {
          failedSheets.push({ index: i, name: sheetName, reason: '未產出案例' });
          continue;
        }
        const prefix = deriveSheetPrefix(sheetName, i);
        const batchCases = processXlsxSheetBatchCases(
          rawCases,
          prefix,
          currentCases.map(c => c['編號']),
          { specFilename: newFile.name, specText: wrapped }
        );
        currentCases = [...currentCases, ...batchCases];
        document.getElementById('step2Text').textContent =
          `全量產出（${batchLabel} 完成，本批 +${batchCases.length}，累計 ${currentCases.length} 筆）`;

        setStep(3, 'running');
        document.getElementById('step3Text').textContent = `更新結果（${currentCases.length} 筆）…`;
        refreshDisplay();
        document.getElementById('resultSection').classList.add('visible');
      } catch (err) {
        const msg = formatApiError(err, { provider: getProviderLabel() });
        failedSheets.push({ index: i, name: sheetName, reason: msg });
        showError(`工作表批次失敗（${sheetName}）：${msg}`);
      }
    }

    lastXlsxSheetBatchState.failedIndices = failedSheets.map(d => d.index);
    showBatchRetryBar(failedSheets, 'sheet');

    currentCases = sortCasesByOutline(currentCases, lastSpecOutline);
    applySpecFullCoverage(newFile, currentCases, selectedSheets);

    setStep(2, 'done');
    setStep(3, 'done');
    document.getElementById('step3Text').textContent =
      appendMode
        ? `附加完成！目前共 ${currentCases.length} 個測試案例`
        : `完成！共產出 ${currentCases.length} 個測試案例${failedSheets.length ? `（${failedSheets.length} 個工作表失敗）` : ''}`;

    refreshDisplay();
    showResultWarnings();
    document.getElementById('resultSection').classList.add('visible');

    try {
      await dbSaveSpec(newFile.name, specTextForPrompt);
      showCacheNotice({
        filename: newFile.name,
        text: specTextForPrompt,
        savedAt: new Date().toLocaleString('zh-TW'),
      });
    } catch (_) {}
  } finally {
    analysisInProgress = false;
    setExportEnabled(true);
  }
}

async function retryFailedXlsxSheetBatches() {
  if (!lastXlsxSheetBatchState?.failedIndices?.length) return;
  const apiKey = document.getElementById('apiKeyInput').value.trim();
  if (!apiKey) { showError(`請填入 ${getApiKeyLabel()}`); return; }

  const { file, selectedSheets, failedIndices } = lastXlsxSheetBatchState;
  analysisInProgress = true;
  setExportEnabled(false);
  document.getElementById('analyzeBtn').disabled = true;
  const stillFailed = [];

  try {
    for (let j = 0; j < failedIndices.length; j++) {
      const i = failedIndices[j];
      const sheetName = selectedSheets[i];
      const batchLabel = `重試工作表 ${i + 1}/${selectedSheets.length}：${sheetName}`;
      if (j > 0) await throttleBetweenBatches(batchLabel);

      const { text: sheetText } = await extractXlsxSpecText(file, [sheetName]);
      const wrapped = wrapSpecDocument(file.name, sheetText);
      const prompt = buildFullPrompt(wrapped);

      try {
        const { cases: rawCases } = await fetchBatchCases(
          apiKey,
          prompt,
          batchLabel,
          { type: 'sheet', name: sheetName }
        );
        if (!rawCases.length) {
          stillFailed.push({ index: i, name: sheetName, reason: '未產出案例' });
          continue;
        }
        const prefix = deriveSheetPrefix(sheetName, i);
        const batchCases = processXlsxSheetBatchCases(
          rawCases,
          prefix,
          currentCases.map(c => c['編號']),
          { specFilename: file.name, specText: wrapped }
        );
        currentCases = [...currentCases, ...batchCases];
        currentCases = sortCasesByFeature(currentCases);
        refreshDisplay();
      } catch (err) {
        const msg = formatApiError(err, { provider: getProviderLabel() });
        stillFailed.push({ index: i, name: sheetName, reason: msg });
        showError(`重試失敗（${sheetName}）：${msg}`);
      }
    }

    lastXlsxSheetBatchState.failedIndices = stillFailed.map(d => d.index);
    showBatchRetryBar(stillFailed, 'sheet');
    currentCases = sortCasesByOutline(currentCases, lastSpecOutline);
    applySpecFullCoverage(file, currentCases, selectedSheets);
    updateCoveragePanel();
    showResultWarnings();
  } finally {
    analysisInProgress = false;
    setExportEnabled(true);
    document.getElementById('analyzeBtn').disabled = false;
    checkReady();
  }
}

async function finishMultiSpecAnalysis({
  apiKey, indexSource, supplementDocs, appendMode
}) {
  const indexName = indexSource.name;
  const indexText = indexSource.text;
  const manualOutline = indexSource.manualOutline || null;

  const useAutoBatch =
    document.getElementById('multiAutoBatch')?.checked !== false &&
    supplementDocs.length >= 2;
  const remarkDup = document.getElementById('multiRemarkDup')?.checked;
  const useAiDup = document.getElementById('multiUseAiDupConfirm')?.checked;

  analysisInProgress = true;
  setExportEnabled(false);
  hideBatchRetryBar();
  lastAiParseWarning = null;
  lastMultiPrdCoverageWarning = null;
  lastXlsxSheetBatchState = null;
  lastMultiBatchState = { indexSource, supplementDocs, failedIndices: [] };
  rebuildMultiOutlines(indexText, supplementDocs, null, manualOutline);

  if (!appendMode) {
    currentCases = [];
    clearResultFilters();
  }

  setStep(2, 'running');
  const failedDocs = [];
  const allNewFromRun = [];

  try {
    if (useAutoBatch) {
      const total = supplementDocs.length;
      for (let i = 0; i < total; i++) {
        const doc = supplementDocs[i];
        const batchLabel = `規格書 ${i + 1}/${total}：${doc.name}`;
        if (i > 0) await throttleBetweenBatches(batchLabel);
        setStep(2, 'running');
        document.getElementById('step2Text').textContent = `${batchLabel}（分析中…）`;

        rebuildMultiOutlines(indexText, supplementDocs, doc, manualOutline);
        const specText = buildMultiSpecBundle(indexName, indexText, [doc]);
        const existingRules = buildExistingRulesSummary(currentCases);
        const prompt = buildMultiBatchPrompt({
          specText,
          indexName,
          currentPrd: doc.name,
          supplementList: supplementDocs.map(d => d.name).join('\n'),
          existingRules
        });

        try {
          const { cases: rawCases, warning } = await fetchBatchCases(apiKey, prompt, batchLabel);
          if (warning && !lastAiParseWarning) lastAiParseWarning = warning;
          if (!rawCases.length) {
            failedDocs.push({ index: i, name: doc.name, reason: '未產出案例' });
            continue;
          }
          const prefix = derivePrdPrefix(doc.name, i);
          const batchCases = await processMultiBatchCases(
            rawCases,
            prefix,
            currentCases.map(c => c['編號']),
            {
              specFilename: doc.name,
              specText: wrapSpecDocument(doc.name, doc.text),
            }
          );
          currentCases = [...currentCases, ...batchCases];
          allNewFromRun.push(...batchCases);
          document.getElementById('step2Text').textContent =
            `${batchLabel} 完成（本批 +${batchCases.length}，累計 ${currentCases.length} 筆）`;

          if (remarkDup) currentCases = markDuplicateSuspects(currentCases);
          currentCases = sortCasesByFeature(currentCases);
          setStep(3, 'running');
          document.getElementById('step3Text').textContent = `更新結果（${currentCases.length} 筆）…`;
          refreshDisplay();
          document.getElementById('resultSection').classList.add('visible');
        } catch (err) {
          const msg = formatApiError(err, { provider: getProviderLabel() });
          failedDocs.push({ index: i, name: doc.name, reason: msg });
          showError(`PRD 批次失敗（${doc.name}）：${msg}`);
        }
      }
      lastMultiBatchState.failedIndices = failedDocs.map(d => d.index);
      showBatchRetryBar(failedDocs);
    } else {
      rebuildMultiOutlines(indexText, supplementDocs, null, manualOutline);
      const specText = buildMultiSpecBundle(indexName, indexText, supplementDocs);
      const prompt = buildMultiSinglePrompt(
        specText,
        supplementDocs.map(d => d.name),
        indexName
      );
      const label = `多規格生成（索引 + ${supplementDocs.length} 份規格書）`;
      const { cases: rawCases } = await fetchBatchCases(apiKey, prompt, label);
      const prefix = derivePrdPrefix(supplementDocs[0]?.name || indexName, 0);
      const batchCases = await processMultiBatchCases(
        rawCases,
        prefix,
        appendMode ? currentCases.map(c => c['編號']) : [],
        supplementDocs.length ? { supplementDocs } : {}
      );
      currentCases = appendMode ? [...currentCases, ...batchCases] : batchCases;
      allNewFromRun.push(...batchCases);
    }

    if (!remarkDup) {
      currentCases = markDuplicateSuspects(currentCases);
    }

    if (useAiDup && currentCases.some(c => c._dupSuspect)) {
      setStep(2, 'running');
      document.getElementById('step2Text').textContent = 'AI 確認模糊重複群組…';
      currentCases = await confirmDuplicateSuspectsWithAi(apiKey, currentCases);
    }

    currentCases = sortCasesByFeature(currentCases);
    if (supplementDocs.length) {
      setCoverageDocNames(supplementDocs.map(d => d.name));
      coverageInspectCases = null;
    }

    setStep(2, 'done');
    setStep(3, 'done');
    document.getElementById('step3Text').textContent =
      `完成！共 ${currentCases.length} 個測試案例${failedDocs.length ? `（${failedDocs.length} 批失敗）` : ''}`;

    refreshDisplay();
    showResultWarnings();
    document.getElementById('resultSection').classList.add('visible');

    try {
      const cacheFilename = `${indexName}${supplementDocs.length ? ` +${supplementDocs.length}份PRD` : ''}`;
      const bundleText = buildMultiSpecBundle(indexName, indexText, supplementDocs);
      await dbSaveSpec(cacheFilename, bundleText);
      showCacheNotice({
        filename: cacheFilename,
        text: bundleText,
        savedAt: new Date().toLocaleString('zh-TW')
      });
    } catch (_) {}
  } finally {
    analysisInProgress = false;
    setExportEnabled(true);
  }
}

async function retryFailedMultiBatches() {
  if (!lastMultiBatchState?.failedIndices?.length) return;
  const apiKey = document.getElementById('apiKeyInput').value.trim();
  if (!apiKey) { showError(`請填入 ${getApiKeyLabel()}`); return; }

  const { indexSource, supplementDocs, failedIndices } = lastMultiBatchState;
  const { name: indexName, text: indexText, manualOutline } = indexSource;
  analysisInProgress = true;
  setExportEnabled(false);
  document.getElementById('analyzeBtn').disabled = true;
  const remarkDup = document.getElementById('multiRemarkDup')?.checked;
  const stillFailed = [];

  try {
    for (let j = 0; j < failedIndices.length; j++) {
      const i = failedIndices[j];
      const doc = supplementDocs[i];
      const batchLabel = `重試規格書 ${i + 1}/${supplementDocs.length}：${doc.name}`;
      if (j > 0) await throttleBetweenBatches(batchLabel);
      rebuildMultiOutlines(indexText, supplementDocs, doc, manualOutline);
      const specText = buildMultiSpecBundle(indexName, indexText, [doc]);
      const prompt = buildMultiBatchPrompt({
        specText,
        indexName,
        currentPrd: doc.name,
        supplementList: supplementDocs.map(d => d.name).join('\n'),
        existingRules: buildExistingRulesSummary(currentCases)
      });
      try {
        const { cases: rawCases } = await fetchBatchCases(apiKey, prompt, batchLabel);
        if (!rawCases.length) {
          stillFailed.push({ index: i, name: doc.name, reason: '未產出案例' });
          continue;
        }
        const prefix = derivePrdPrefix(doc.name, i);
        const batchCases = await processMultiBatchCases(
          rawCases,
          prefix,
          currentCases.map(c => c['編號']),
          {
            specFilename: doc.name,
            specText: wrapSpecDocument(doc.name, doc.text),
          }
        );
        currentCases = [...currentCases, ...batchCases];
        if (remarkDup) currentCases = markDuplicateSuspects(currentCases);
        currentCases = sortCasesByFeature(currentCases);
        refreshDisplay();
      } catch (err) {
        const msg = formatApiError(err, { provider: getProviderLabel() });
        stillFailed.push({ index: i, name: doc.name, reason: msg });
        showError(`重試失敗（${doc.name}）：${msg}`);
      }
    }
    lastMultiBatchState.failedIndices = stillFailed.map(d => d.index);
    showBatchRetryBar(stillFailed);
    if (!remarkDup && currentCases.length) {
      currentCases = markDuplicateSuspects(currentCases);
      refreshDisplay();
    }
    lastMultiPrdCoverageWarning = checkMultiPrdCoverage(supplementDocs, currentCases);
    if (supplementDocs?.length) {
      setCoverageDocNames(supplementDocs.map(d => d.name));
    }
    updateCoveragePanel();
    showResultWarnings();
  } finally {
    analysisInProgress = false;
    setExportEnabled(true);
    document.getElementById('analyzeBtn').disabled = false;
    checkReady();
  }
}

function updateDeleteSelectedBtn() {
  const btn = document.getElementById('deleteSelectedBtn');
  if (!btn) return;
  const n = selectedCaseIds.size;
  if (n > 0 && currentCases.length > 0) {
    btn.style.display = 'inline-flex';
    btn.textContent = `🗑 刪除選取（${n} 筆）`;
  } else {
    btn.style.display = 'none';
  }
}

function syncSelectAllCheckbox() {
  const selAll = document.getElementById('selectAllCases');
  if (!selAll) return;
  const filtered = filterCases(currentCases);
  const ids = filtered.map(c => c['編號']).filter(Boolean);
  if (!ids.length) {
    selAll.checked = false;
    selAll.indeterminate = false;
    return;
  }
  const selectedCount = ids.filter(id => selectedCaseIds.has(id)).length;
  selAll.checked = selectedCount === ids.length;
  selAll.indeterminate = selectedCount > 0 && selectedCount < ids.length;
}

function deleteSelectedCases() {
  if (!selectedCaseIds.size) {
    showError('請先勾選要刪除的案例');
    return;
  }
  const ids = [...selectedCaseIds];
  const preview = ids.slice(0, 5).join('、') + (ids.length > 5 ? '…' : '');
  if (!confirm(`確定刪除 ${ids.length} 筆案例？\n${preview}`)) return;
  const idSet = new Set(ids);
  currentCases = currentCases.filter(c => !idSet.has(c['編號']));
  currentCases = markDuplicateSuspects(currentCases);
  currentCases = sortCasesByFeature(currentCases);
  selectedCaseIds = new Set([...selectedCaseIds].filter(id => !idSet.has(id)));
  const selAll = document.getElementById('selectAllCases');
  if (selAll) selAll.checked = false;
  const selAllDup = document.getElementById('selectAllDup');
  if (selAllDup) selAllDup.checked = false;
  if (resultView === 'duplicate' && !hasDuplicateSuspects()) resultView = 'table';
  if (analysisMode === 'mindmap') {
    if (currentCases.length) syncMindmapExportFromCases();
    else lastMindmapExport = null;
  }
  refreshDisplay();
}

// ─── 規格書多格式提取 / XLSX 工作表 UI ───────────────────────
const xlsxSheetCache = new Map();
let xlsxSheetUi = { inputId: 'newFile', fileKey: null, sheets: [], selected: new Set() };
let lastSpecExtractSummary = '';

function isFileXlsxSheetReady(file) {
  if (!file || getSpecFormat(file) !== 'xlsx') return true;
  const key = getSpecFileKey(file);
  const cached = xlsxSheetCache.get(key);
  if (cached?.size) return true;
  return xlsxSheetUi.fileKey === key && xlsxSheetUi.selected.size > 0;
}

function areSupplementXlsxFilesReady() {
  const xlsxFiles = getSupplementFiles().filter(f => getSpecFormat(f) === 'xlsx');
  if (!xlsxFiles.length) return true;
  return xlsxFiles.every(f => isFileXlsxSheetReady(f));
}

function getXlsxFilesNeedingSheetUi() {
  const out = [];
  if (analysisMode === 'multi') {
    for (const file of getSupplementFiles()) {
      if (getSpecFormat(file) === 'xlsx') {
        out.push({ file, inputId: 'supplementFiles', role: 'prd' });
      }
    }
    const newFile = document.getElementById('newFile')?.files?.[0];
    if (newFile && getSpecFormat(newFile) === 'xlsx') {
      out.push({ file: newFile, inputId: 'newFile', role: 'index' });
    }
    return out;
  }
  const newFile = document.getElementById('newFile')?.files?.[0];
  if (newFile && getSpecFormat(newFile) === 'xlsx') {
    out.push({ file: newFile, inputId: 'newFile', role: 'spec' });
  }
  return out;
}

function hideXlsxSheetPanel() {
  document.getElementById('xlsxSheetPanel')?.classList.remove('visible');
  const picker = document.getElementById('xlsxSheetFilePicker');
  if (picker) {
    picker.style.display = 'none';
    picker.innerHTML = '';
  }
  xlsxSheetUi = { inputId: 'newFile', fileKey: null, sheets: [], selected: new Set() };
}

function updateXlsxSheetHint() {
  const el = document.getElementById('xlsxSheetHint');
  if (!el) return;
  if (analysisMode === 'multi') {
    el.innerHTML = 'PRD 或模組索引為 XLSX 時，請勾選要納入分析的工作表；建議略過的項目已預設取消。多份 XLSX 請用下方標籤切換檔案，<strong>每份至少勾選 1 個工作表</strong>。';
  } else {
    el.innerHTML = '工作表名稱因檔案而異；建議略過的項目已預設取消勾選。勾選 <strong>2 個以上</strong>工作表時，全量產出將<strong>逐工作表分批</strong>呼叫 API。';
  }
}

async function ensureXlsxSheetCache(file) {
  const key = getSpecFileKey(file);
  if (xlsxSheetCache.has(key)) return;
  const sheets = await listXlsxSheets(file);
  let selected = new Set(sheets.filter(s => !suggestSkipSheet(s.name)).map(s => s.name));
  if (!selected.size) selected = new Set(sheets.map(s => s.name));
  xlsxSheetCache.set(key, selected);
}

async function syncXlsxSheetPanel(preferredFileKey = null) {
  const candidates = getXlsxFilesNeedingSheetUi();
  if (!candidates.length) {
    hideXlsxSheetPanel();
    return;
  }
  for (const c of candidates) {
    await ensureXlsxSheetCache(c.file);
  }
  let active = preferredFileKey
    ? candidates.find(c => getSpecFileKey(c.file) === preferredFileKey)
    : null;
  if (!active && xlsxSheetUi.fileKey) {
    active = candidates.find(c => getSpecFileKey(c.file) === xlsxSheetUi.fileKey);
  }
  if (!active) active = candidates[0];
  await showXlsxSheetPanelForFile(active.file, active.inputId, candidates);
}

async function getXlsxSelectedSheets(file) {
  const key = getSpecFileKey(file);
  if (xlsxSheetUi.fileKey === key && xlsxSheetUi.selected.size) {
    return [...xlsxSheetUi.selected];
  }
  const cached = xlsxSheetCache.get(key);
  if (cached?.size) return [...cached];

  const sheets = await listXlsxSheets(file);
  const allNames = sheets.map(s => s.name);
  const auto = allNames.filter(n => !suggestSkipSheet(n));
  return auto.length ? auto : allNames;
}

async function extractSpecFile(file, inputId) {
  const options = {};
  if (getSpecFormat(file) === 'xlsx') {
    options.selectedSheets = await getXlsxSelectedSheets(file);
  }
  const result = await extractSpecText(file, options);
  return result;
}

async function handleSpecFileChange(inputId, file) {
  if (!file) {
    if (inputId === 'newFile') await syncXlsxSheetPanel();
    return;
  }
  if (!isSpecFile(file)) {
    throw new Error('不支援的規格格式，請使用 PDF、DOCX、XLSX 或 CSV');
  }
  if (inputId === 'newFile' && getSpecFormat(file) === 'xlsx') {
    await syncXlsxSheetPanel(getSpecFileKey(file));
    return;
  }
  if (inputId === 'newFile') await syncXlsxSheetPanel();
}

async function handleSupplementFilesChange() {
  if (analysisMode !== 'multi') return;
  await syncXlsxSheetPanel();
}

function renderXlsxSheetFilePicker(candidates) {
  const picker = document.getElementById('xlsxSheetFilePicker');
  if (!picker) return;
  if (candidates.length <= 1) {
    picker.style.display = 'none';
    picker.innerHTML = '';
    return;
  }
  picker.style.display = 'flex';
  const currentKey = xlsxSheetUi.fileKey;
  picker.innerHTML = candidates.map((c, idx) => {
    const key = getSpecFileKey(c.file);
    const active = key === currentKey ? ' active' : '';
    const tag = c.role === 'index' ? '索引' : (c.role === 'prd' ? 'PRD' : '');
    const tagHtml = tag ? ` <span class="sheet-meta">${tag}</span>` : '';
    return `<button type="button" class="xlsx-sheet-file-chip${active}" data-file-idx="${idx}">${escapeHtml(c.file.name)}${tagHtml}</button>`;
  }).join('');

  picker.querySelectorAll('.xlsx-sheet-file-chip').forEach(btn => {
    btn.addEventListener('click', () => {
      const idx = Number(btn.dataset.fileIdx);
      const target = candidates[idx];
      if (!target) return;
      showXlsxSheetPanelForFile(target.file, target.inputId, candidates).catch(err => {
        showError(err.message);
      });
    });
  });
}

async function showXlsxSheetPanelForFile(file, inputId, allCandidates = null) {
  const sheets = await listXlsxSheets(file);
  const key = getSpecFileKey(file);
  await ensureXlsxSheetCache(file);
  let selected = xlsxSheetCache.get(key);
  selected = selected ? new Set(selected) : new Set();

  const candidates = allCandidates || getXlsxFilesNeedingSheetUi();
  xlsxSheetUi = { inputId, fileKey: key, sheets, selected };
  const panel = document.getElementById('xlsxSheetPanel');
  const roleLabel = inputId === 'supplementFiles' ? 'PRD' : (analysisMode === 'multi' ? '模組索引' : '規格書');
  document.getElementById('xlsxSheetTitle').textContent = `📑 工作表（${roleLabel}）：${file.name}`;
  updateXlsxSheetHint();
  renderXlsxSheetFilePicker(candidates);
  renderXlsxSheetList();
  panel?.classList.add('visible');
  checkReady();
}

function renderXlsxSheetList() {
  const list = document.getElementById('xlsxSheetList');
  if (!list) return;
  const { sheets, selected, fileKey } = xlsxSheetUi;
  list.innerHTML = sheets.map((s, idx) => {
    const skip = suggestSkipSheet(s.name);
    const checked = selected.has(s.name) ? 'checked' : '';
    const cls = skip ? 'xlsx-sheet-item suggested-skip' : 'xlsx-sheet-item';
    return `<label class="${cls}"><input type="checkbox" data-sheet-idx="${idx}" ${checked} /> ${escapeHtml(s.name)} <span class="sheet-meta">（約 ${s.rowCount} 列）</span></label>`;
  }).join('');

  list.querySelectorAll('input[type="checkbox"]').forEach(cb => {
    cb.addEventListener('change', () => {
      const idx = Number(cb.dataset.sheetIdx);
      const name = sheets[idx]?.name;
      if (!name) return;
      if (cb.checked) xlsxSheetUi.selected.add(name);
      else xlsxSheetUi.selected.delete(name);
      xlsxSheetCache.set(fileKey, new Set(xlsxSheetUi.selected));
      checkReady();
    });
  });
}

function initXlsxSheetPanelButtons() {
  document.getElementById('xlsxSheetSelectAll')?.addEventListener('click', () => {
    xlsxSheetUi.selected = new Set(xlsxSheetUi.sheets.map(s => s.name));
    xlsxSheetCache.set(xlsxSheetUi.fileKey, new Set(xlsxSheetUi.selected));
    renderXlsxSheetList();
    checkReady();
  });
  document.getElementById('xlsxSheetSelectNone')?.addEventListener('click', () => {
    xlsxSheetUi.selected = new Set();
    xlsxSheetCache.set(xlsxSheetUi.fileKey, new Set());
    renderXlsxSheetList();
    checkReady();
  });
  document.getElementById('xlsxSheetSelectSuggested')?.addEventListener('click', () => {
    const picked = xlsxSheetUi.sheets.filter(s => !suggestSkipSheet(s.name)).map(s => s.name);
    xlsxSheetUi.selected = new Set(picked.length ? picked : xlsxSheetUi.sheets.map(s => s.name));
    xlsxSheetCache.set(xlsxSheetUi.fileKey, new Set(xlsxSheetUi.selected));
    renderXlsxSheetList();
    checkReady();
  });
}

function showSpecExtractNote(summary) {
  const el = document.getElementById('specParseNote');
  if (!el) return;
  if (!summary) {
    el.style.display = 'none';
    el.textContent = '';
    return;
  }
  el.textContent = `✓ 規格解析：${summary}`;
  el.style.display = 'block';
}

// ─── 解析 AI 回傳的 JSON ─────────────────────────────────────
function updateLlmModelNote() {
  const noteEl = document.getElementById('llmModelNote');
  if (!noteEl) return;
  const provider = getLlmProvider();
  const models = getModelsForProvider(provider);
  const model = models.find(m => m.id === getSelectedModelId(provider)) || models[0];
  noteEl.innerHTML =
    `<strong>優點：</strong>${model.pros}<br><strong>缺點：</strong>${model.cons}`;
}

function rebuildModelSelect() {
  const provider = getLlmProvider();
  const models = getModelsForProvider(provider);
  const sel = document.getElementById('llmModelSelect');
  if (!sel) return;
  sel.innerHTML = renderModelOptions(models);
  const saved = localStorage.getItem(getModelStorageKey(provider));
  sel.value = (saved && models.some(m => m.id === saved))
    ? saved
    : getDefaultModelForProvider(provider);
  updateLlmModelNote();
}

function closeApiHelpBoxes() {
  document.getElementById('apiHelpBox')?.classList.remove('visible');
  document.getElementById('sirayaHelpBox')?.classList.remove('visible');
  const btn = document.getElementById('helpKeyBtn');
  if (btn) btn.textContent = '❓ 如何取得 Key ▾';
}

function updateProviderUi() {
  const provider = getLlmProvider();
  const isSiraya = provider === PROVIDER_SIRAYA;
  document.getElementById('apiKeyLabel').textContent =
    `${getApiKeyLabel(provider)}（儲存於本機，不會上傳）`;
  document.getElementById('apiKeyInput').placeholder = isSiraya ? 'sk-...' : 'AIzaSy...';
  document.getElementById('llmModelLabel').textContent = isSiraya
    ? 'AI 模型（Siraya：Gemini / GPT / Claude）'
    : 'AI 模型（同一 API Key，各模型額度分開計算）';
  closeApiHelpBoxes();
}

function loadApiKeyForProvider(provider) {
  const saved = localStorage.getItem(getApiKeyStorageKey(provider));
  document.getElementById('apiKeyInput').value = saved || '';
}

/** @param {'gemini'|'siraya'} provider */
function persistApiKeyForProvider(provider, key) {
  const storageKey = getApiKeyStorageKey(provider);
  if (key) localStorage.setItem(storageKey, key);
  else localStorage.removeItem(storageKey);
}

/** 切換提供者前記住的是哪一個，避免 change 後存到錯誤的 key */
let activeLlmProvider = PROVIDER_GEMINI;

function initLlmSettings() {
  const providerSel = document.getElementById('llmProviderSelect');
  const modelSel = document.getElementById('llmModelSelect');
  if (!providerSel || !modelSel) return;

  const savedProvider = localStorage.getItem(LLM_PROVIDER_STORAGE_KEY);
  if (savedProvider === PROVIDER_GEMINI || savedProvider === PROVIDER_SIRAYA) {
    providerSel.value = savedProvider;
  }

  activeLlmProvider = getLlmProvider();
  loadApiKeyForProvider(activeLlmProvider);
  updateProviderUi();
  rebuildModelSelect();

  providerSel.addEventListener('change', () => {
    persistApiKeyForProvider(activeLlmProvider, document.getElementById('apiKeyInput').value.trim());

    activeLlmProvider = providerSel.value;
    localStorage.setItem(LLM_PROVIDER_STORAGE_KEY, activeLlmProvider);
    loadApiKeyForProvider(activeLlmProvider);
    updateProviderUi();
    rebuildModelSelect();
    checkReady();
  });

  modelSel.addEventListener('change', () => {
    localStorage.setItem(getModelStorageKey(), modelSel.value);
    updateLlmModelNote();
  });
}

// ─── 解析 AI 回傳的 JSON ─────────────────────────────────────
function parseLlmJsonArray(rawText) {
  let cleaned = rawText.replace(/```json|```/g, '').trim();
  cleaned = repairJsonControlChars(cleaned);
  const { text: safeText, truncated } = fixTruncatedJson(cleaned);
  let parsed;
  try {
    parsed = JSON.parse(safeText);
  } catch (err) {
    throw new Error(`AI 回傳 JSON 無法解析：${err.message}`);
  }
  if (!Array.isArray(parsed)) throw new Error('AI 回傳的不是陣列');
  return { parsed, truncated };
}

function parseAiJson(rawText, truncateContext) {
  lastAiParseWarning = null;
  const { parsed, truncated } = parseLlmJsonArray(rawText);
  if (truncated) {
    lastAiParseWarning = formatTruncationWarning(parsed.length, truncateContext);
  }
  return parsed.map(entry => normalizeCaseEntry(entry, lastSpecOutline));
}

const REFILL_BATCH_SIZE = 20;

function chunkArray(arr, size) {
  const out = [];
  for (let i = 0; i < arr.length; i += size) out.push(arr.slice(i, i + size));
  return out;
}

function buildRefillSummary(cases) {
  return cases.map(c => ({
    '編號': c['編號'] || '',
    '主模組': c['主模組'] || '',
    '層級': c['層級'] || '',
    '功能頁面/元件': c['功能頁面/元件'] || '',
    '前置條件': c['前置條件'] || '',
    '測試標題': c['測試標題'] || '',
    '預期結果': c['預期結果'] || '',
    '規格來源': c['規格來源'] || '',
    '優先度': c['優先度'] || '',
  }));
}

function mergeRefillIntoCases(cases, refillMap) {
  return cases.map(c => {
    const r = refillMap.get(c['編號']);
    if (!r) return c;
    return normalizeCaseEntry({
      ...c,
      '主模組': c['主模組'] || r['主模組'] || '',
      '層級': c['層級'] || r['層級'] || '',
      '功能頁面/元件': c['功能頁面/元件'] || r['功能頁面/元件'] || '',
      '前置條件': c['前置條件'] || r['前置條件'] || '',
      '測試標題': c['測試標題'] || r['測試標題'] || '',
      '預期結果': c['預期結果'] || r['預期結果'] || '',
      '規格來源': c['規格來源'] || r['規格來源'] || '',
      '優先度': c['優先度'] || r['優先度'] || '',
    }, lastSpecOutline);
  });
}

function normalizeCaseId(id) {
  const s = (id || '').trim();
  if (!s) return '';
  const m = s.match(/([A-Z]{3}_[A-Z]{3,6}_\d{3,})$/);
  return m ? m[1] : s;
}

function sanitizeImportedCase(entry) {
  return normalizeCaseEntry({ ...entry, '狀態': entry['狀態'] || '有效' }, lastSpecOutline);
}

function dedupeCasesWithObsoleteMark(cases) {
  const byBaseId = new Map();
  cases.forEach((c, idx) => {
    const base = normalizeCaseId(c['編號']) || `__idx_${idx}`;
    if (!byBaseId.has(base)) byBaseId.set(base, []);
    byBaseId.get(base).push(c);
  });

  const result = [];
  byBaseId.forEach(list => {
    if (list.length === 1) {
      result.push(list[0]);
      return;
    }
    // 保留最新（最後一筆）
    for (let i = 0; i < list.length - 1; i++) {
      result.push({ ...list[i], _obsolete: true, _replacedBy: list[list.length - 1]['編號'] || null });
    }
    result.push(list[list.length - 1]);
  });
  return result;
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
  return (name || '')
    .toString()
    .replace(/^\uFEFF/, '')   // BOM
    .replace(/\r|\n/g, '')    // 換行
    .replace(/\u3000/g, ' ')  // 全形空白
    .trim();
}

async function loadBaselineCasesFromFile(file) {
  const required = ['編號', '測試類型', '類別', '優先度', '主模組', '層級', '功能頁面/元件', '前置條件', '測試標題', '預期結果', '規格來源', '版本標籤'];
  const requiredNorm = required.map(normalizeHeaderName);
  let rows = [];
  let sourceHeaders = [];

  if (file.name.toLowerCase().endsWith('.csv')) {
    const text = await file.text();
    const lines = text.split(/\r?\n/).filter(l => l.trim() !== '');
    if (lines.length < 2) throw new Error('CSV 內容不足，至少需要標題列與 1 筆資料');
    const headers = parseCsvLine(lines[0]).map(normalizeHeaderName);
    sourceHeaders = headers;
    rows = lines.slice(1).map(line => {
      const cols = parseCsvLine(line);
      const obj = {};
      headers.forEach((h, i) => { obj[h] = cols[i] || ''; });
      return obj;
    });
  } else if (file.name.toLowerCase().endsWith('.xlsx')) {
    const wb = new ExcelJS.Workbook();
    const buf = await file.arrayBuffer();
    await wb.xlsx.load(buf);
    const ws = wb.worksheets[0];
    if (!ws) throw new Error('XLSX 讀取失敗：找不到工作表');
    const headerRow = ws.getRow(1).values.slice(1).map(v => normalizeHeaderName(v || ''));
    sourceHeaders = headerRow;
    rows = [];
    ws.eachRow((row, idx) => {
      if (idx === 1) return;
      const vals = row.values.slice(1);
      const obj = {};
      headerRow.forEach((h, i) => { obj[h] = (vals[i] || '').toString().trim(); });
      rows.push(obj);
    });
    rows = rows.filter(r => Object.values(r).some(v => (v || '').trim() !== ''));
  } else {
    throw new Error('Baseline 檔案僅支援 CSV 或 XLSX');
  }

  const sourceSet = new Set(sourceHeaders.map(normalizeHeaderName));
  const missing = required.filter((k, i) => !sourceSet.has(requiredNorm[i]));
  if (missing.length > 0) throw new Error(`Baseline 缺少必要欄位：${missing.join('、')}`);
  return rows.map(sanitizeImportedCase);
}

// ─── XLSX 轉心智圖 ───────────────────────────────────────────
let lastMindmapExport = null; // { tree, mermaid, markdown, validCount, skippedCount }
/** 離開心智圖模式時保留樹資料與瀏覽狀態，切回時還原 */
let mindmapSessionCache = null; // { export, navSelection, subView, collapsedCards, resultView }
let mindmapNavSelection = null; // { nodePath: string[] }
let mindmapSubView = 'browse';
let mindmapPlatformCaseMap = new Map();
let mindmapCollapsedCards = new Set();

async function copyTextWithFeedback(text, btn, okLabel) {
  try {
    await navigator.clipboard.writeText(text);
    if (btn) {
      const prev = btn.textContent;
      btn.textContent = okLabel || '✅ 已複製';
      setTimeout(() => { btn.textContent = prev; }, 1200);
    }
    return true;
  } catch (_) {
    alert('複製失敗，請手動選取文字複製');
    return false;
  }
}

function prioClass(p) {
  if ((p || '').includes('P0')) return 'p0';
  if ((p || '').includes('P1')) return 'p1';
  if ((p || '').includes('P2')) return 'p2';
  return '';
}

function isMindmapCardCollapsed(pcId) {
  return mindmapCollapsedCards.has(pcId);
}

function renderPlatformCaseCard(pc, opts = {}) {
  const collapsed = isMindmapCardCollapsed(pc.id);
  const stepsHtml = pc.steps.map(s =>
    `<li>${escapeHtml(s.action)} <span style="color:var(--muted)">→</span> ${escapeHtml(s.expected)}</li>`
  ).join('');
  const specSrc = pc.description
    ? `<div class="mm-case-desc" title="規格來源">規格來源：${escapeHtml(pc.description)}</div>`
    : '';
  const pre = pc.precondition && pc.precondition !== '無'
    ? `<div class="mm-case-pre">前置：${escapeHtml(pc.precondition)}</div>`
    : '';
  const rawHint = (pc.rawFeatures?.length > 1 || (pc.rawFeatures?.[0] && pc.rawFeatures[0] !== pc.fullFeature))
    ? `<div class="mm-case-raw-hint" title="原始功能欄位">功能欄位：${escapeHtml(pc.rawFeatures.join('、'))}</div>`
    : '';
  const copyBtns = opts.showCopy !== false
    ? `<div class="mm-card-actions">
         <button type="button" class="mm-copy-platform" data-pc-id="${escapeHtml(pc.id)}">📋 複製給工作平台</button>
         <button type="button" class="mm-copy-steps" data-pc-id="${escapeHtml(pc.id)}">📋 僅複製步驟</button>
       </div>`
    : '';
  const stepCount = pc.steps.length;
  return `<div class="mm-case-card${collapsed ? ' collapsed' : ''}" data-pc-id="${escapeHtml(pc.id)}">
    <div class="mm-case-card-head" role="button" tabindex="0" aria-expanded="${!collapsed}">
      <button type="button" class="mm-card-toggle" aria-label="${collapsed ? '展開' : '收合'}">${collapsed ? '▶' : '▼'}</button>
      <span class="mm-card-icon">📋</span>
      <div class="mm-case-card-title">${escapeHtml(pc.caseTitle)}</div>
      <span class="mm-card-step-badge">${stepCount} 步</span>
      <span class="mm-prio ${prioClass(pc.priority)}">${escapeHtml(pc.priority)}</span>
    </div>
    <div class="mm-case-card-body">
      ${specSrc}
      ${rawHint}
      ${pre}
      <div class="mm-steps-label">測試步驟：</div>
      <ol class="mm-steps">${stepsHtml}</ol>
      ${copyBtns}
    </div>
  </div>`;
}

function renderMindmapNav(roots, filterText) {
  const host = document.getElementById('mindmapNavTree');
  if (!host) return;
  const q = (filterText || '').toLowerCase().trim();
  const parts = [];

  function walk(node, path, depth) {
    const label = path.join(' › ');
    const caseN = countPlatformCasesInNavNode(node);
    const rowN = countRowsInNavNode(node);
    const matchSelf = !q || label.toLowerCase().includes(q)
      || node.cases.some(pc =>
        pc.caseTitle.toLowerCase().includes(q) ||
        pc.description.toLowerCase().includes(q)
      );
    let childHtml = '';
    let childMatch = false;
    for (const ch of node.children) {
      const sub = walk(ch, [...path, ch.name], depth + 1);
      if (sub.matched) childMatch = true;
      childHtml += sub.html;
    }
    if (!matchSelf && !childMatch) return { matched: false, html: '' };
    const isActive = mindmapNavSelection &&
      mindmapNavSelection.join(' › ') === label;
    const indent = `mm-nav-indent-${Math.min(depth, 3)}`;
    const icon = node.type === 'main' ? '📦' : '📁';
    const html = `<div class="mm-nav-item ${indent}${isActive ? ' active' : ''}" data-nav-path="${escapeHtml(label)}" title="${escapeHtml(label)}">
      <span>${icon}</span><span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${escapeHtml(node.name)}</span>
      <span class="mm-badge">${caseN}/${rowN}</span>
    </div>${childHtml}`;
    return { matched: true, html };
  }

  for (const root of roots) {
    const r = walk(root, [root.name], 0);
    if (r.matched) parts.push(r.html);
  }
  host.innerHTML = parts.length ? parts.join('') : '<div style="font-size:12px;color:var(--muted);padding:8px;">無符合項目</div>';
  host.querySelectorAll('.mm-nav-item').forEach(el => {
    el.addEventListener('click', () => {
      const p = el.dataset.navPath;
      mindmapNavSelection = p ? p.split(' › ') : null;
      renderMindmapNav(roots, document.getElementById('mindmapNavSearch')?.value);
      renderMindmapDetail(lastMindmapExport?.tree);
    });
  });
}

function renderMindmapDetail(tree) {
  const titleEl = document.getElementById('mindmapDetailTitle');
  const cardsEl = document.getElementById('mindmapDetailCards');
  const copyAllBtn = document.getElementById('mindmapCopyAllBtn');
  if (!tree || !cardsEl) return;

  const actionsEl = document.getElementById('mindmapDetailActions');

  if (!mindmapNavSelection?.length) {
    if (titleEl) titleEl.textContent = '請從左側選擇節點';
    cardsEl.innerHTML = '<div style="font-size:12px;color:var(--muted);">選擇主模組或資料夾以檢視合併後的平台案例卡</div>';
    if (actionsEl) actionsEl.style.display = 'none';
    return;
  }

  const node = findNavNodeByPath(tree.roots, mindmapNavSelection);
  if (!node) {
    if (titleEl) titleEl.textContent = '節點不存在於此次產出';
    cardsEl.innerHTML = '<div style="font-size:12px;color:var(--muted);">請從左側重新選擇節點</div>';
    if (actionsEl) actionsEl.style.display = 'none';
    return;
  }
  const cases = collectPlatformCasesFromNavNode(node);
  if (titleEl) {
    titleEl.textContent = `${mindmapNavSelection.join(' › ')}（${cases.length} 張案例卡，${countRowsInNavNode(node)} 筆原始列）`;
  }
  cardsEl.innerHTML = cases.map(pc => renderPlatformCaseCard(pc)).join('');
  if (actionsEl) actionsEl.style.display = cases.length ? 'flex' : 'none';
  if (copyAllBtn) {
    copyAllBtn.onclick = () => copyTextWithFeedback(formatPlatformCasesCopy(cases), copyAllBtn, '✅ 已複製全部');
  }
  bindMindmapCardInteractions(cardsEl);
}

function refreshMindmapCardsCollapseUi(container) {
  container.querySelectorAll('.mm-case-card[data-pc-id]').forEach(card => {
    const pcId = card.dataset.pcId;
    const collapsed = isMindmapCardCollapsed(pcId);
    card.classList.toggle('collapsed', collapsed);
    const head = card.querySelector('.mm-case-card-head');
    const btn = card.querySelector('.mm-card-toggle');
    if (head) head.setAttribute('aria-expanded', String(!collapsed));
    if (btn) {
      btn.textContent = collapsed ? '▶' : '▼';
      btn.setAttribute('aria-label', collapsed ? '展開' : '收合');
    }
  });
}

function getActiveMindmapCardsContainer() {
  if (mindmapSubView === 'tree') return document.getElementById('mindmapTreeView');
  return document.getElementById('mindmapDetailCards');
}

function toggleMindmapCardCollapse(pcId) {
  if (mindmapCollapsedCards.has(pcId)) mindmapCollapsedCards.delete(pcId);
  else mindmapCollapsedCards.add(pcId);
}

function setAllMindmapCardsCollapsed(container, collapsed) {
  container.querySelectorAll('.mm-case-card[data-pc-id]').forEach(card => {
    const id = card.dataset.pcId;
    if (collapsed) mindmapCollapsedCards.add(id);
    else mindmapCollapsedCards.delete(id);
  });
}

function bindMindmapCardInteractions(container) {
  bindMindmapCopyButtons(container);
  container.querySelectorAll('.mm-case-card-head').forEach(head => {
    const card = head.closest('.mm-case-card');
    const pcId = card?.dataset.pcId;
    if (!pcId) return;
    const toggle = () => {
      toggleMindmapCardCollapse(pcId);
      const collapsed = isMindmapCardCollapsed(pcId);
      card.classList.toggle('collapsed', collapsed);
      head.setAttribute('aria-expanded', String(!collapsed));
      const btn = head.querySelector('.mm-card-toggle');
      if (btn) {
        btn.textContent = collapsed ? '▶' : '▼';
        btn.setAttribute('aria-label', collapsed ? '展開' : '收合');
      }
    };
    head.addEventListener('click', (ev) => {
      if (ev.target.closest('.mm-card-actions, .mm-copy-platform, .mm-copy-steps')) return;
      toggle();
    });
    head.addEventListener('keydown', (ev) => {
      if (ev.key === 'Enter' || ev.key === ' ') {
        ev.preventDefault();
        toggle();
      }
    });
  });
}

function bindMindmapCopyButtons(container) {
  container.querySelectorAll('.mm-copy-platform').forEach(btn => {
    btn.addEventListener('click', () => {
      const pc = mindmapPlatformCaseMap.get(btn.dataset.pcId);
      if (pc) copyTextWithFeedback(formatPlatformCaseCopy(pc), btn, '✅ 已複製');
    });
  });
  container.querySelectorAll('.mm-copy-steps').forEach(btn => {
    btn.addEventListener('click', () => {
      const pc = mindmapPlatformCaseMap.get(btn.dataset.pcId);
      if (!pc) return;
      const text = pc.steps.map((s, i) =>
        `${i + 1}. 動作：${s.action}\n   預期：${s.expected}`
      ).join('\n');
      copyTextWithFeedback(text, btn, '✅ 已複製');
    });
  });
}

function renderMindmapTreeOverview(tree) {
  const host = document.getElementById('mindmapTreeView');
  if (!host || !tree) return;
  const sections = tree.roots.map(root => {
    const branches = collectPlatformCasesFromNavNode(root).map(pc => {
      const folders = pc.folderPath.map(f =>
        `<span class="mm-folder-pill">📁 ${escapeHtml(f)}</span><span class="mm-tree-connector">→</span>`
      ).join('');
      return `<div class="mm-tree-branch">
        <span class="mm-folder-pill">📦 ${escapeHtml(pc.mainModule)}</span>
        <span class="mm-tree-connector">→</span>
        ${folders}
        ${renderPlatformCaseCard(pc)}
      </div>`;
    }).join('');
    return `<div class="mm-tree-main">
      <div class="mm-tree-main-title">${escapeHtml(root.name)}（${countPlatformCasesInNavNode(root)} 卡 / ${countRowsInNavNode(root)} 列）</div>
      ${branches}
    </div>`;
  });
  host.innerHTML = sections.join('') || '<div style="color:var(--muted);font-size:13px;">無案例</div>';
  bindMindmapCardInteractions(host);
}

function assignMindmapExport(tree, sourceCaseCount = null) {
  lastMindmapExport = {
    tree,
    mermaid: treeToMermaidFlowchart(tree),
    markdown: treeToMarkdownOutline(tree),
    validCount: tree.validCount,
    skippedCount: tree.skippedCount,
    sourceCaseCount: sourceCaseCount ?? tree.validCount,
  };
  if (mindmapSessionCache) mindmapSessionCache.export = lastMindmapExport;
  return lastMindmapExport;
}

function getModuleIndexFilenames() {
  // 僅多規格模式需剝除模組索引檔名；單檔 spec 全量勿把 newFile 當索引（會誤剝 XLSX 規格書檔名）
  if (analysisMode !== 'multi') return [];
  const names = [];
  const file = document.getElementById('newFile')?.files?.[0];
  if (file?.name) names.push(file.name);
  if (lastSpecSourceFilename) {
    const base = lastSpecSourceFilename.replace(/\s*\+.*$/, '').trim();
    if (base && !names.includes(base)) names.push(base);
  }
  return names;
}

function syncMindmapExportFromCases(cases = currentCases) {
  if (!cases?.length) return null;
  const tree = buildMindMapTree(cases, { indexNames: getModuleIndexFilenames() });
  assignMindmapExport(tree, cases.length);
  return tree;
}

function ensureMindmapNavSelection(tree) {
  if (!tree?.roots?.length) {
    mindmapNavSelection = null;
    return;
  }
  if (!mindmapNavSelection || !findNavNodeByPath(tree.roots, mindmapNavSelection)) {
    mindmapNavSelection = [tree.roots[0].name];
  }
}

function syncMindmapSubViewDisplay() {
  const view = mindmapSubView;
  document.getElementById('mindmapTabBrowse')?.classList.toggle('active', view === 'browse');
  document.getElementById('mindmapTabTree')?.classList.toggle('active', view === 'tree');
  const browse = document.getElementById('mindmapBrowseView');
  const treeEl = document.getElementById('mindmapTreeView');
  const treeCollapseBtn = document.getElementById('mindmapTreeCollapseAllBtn');
  const treeExpandBtn = document.getElementById('mindmapTreeExpandAllBtn');
  if (browse) browse.style.display = view === 'browse' ? '' : 'none';
  if (treeEl) treeEl.style.display = view === 'tree' ? 'block' : 'none';
  if (treeCollapseBtn) treeCollapseBtn.style.display = view === 'tree' ? 'inline-flex' : 'none';
  if (treeExpandBtn) treeExpandBtn.style.display = view === 'tree' ? 'inline-flex' : 'none';
}

function refreshMindmapResultView() {
  let tree = lastMindmapExport?.tree;
  if (!tree && analysisMode === 'mindmap' && currentCases.length) {
    tree = syncMindmapExportFromCases();
  }
  if (!tree) return;
  ensureMindmapNavSelection(tree);
  syncMindmapSubViewDisplay();
  renderMindmapViews(tree);
}

function setMindmapSubView(view) {
  mindmapSubView = view;
  refreshMindmapResultView();
}

function renderMindmapViews(tree) {
  if (!tree) return;
  mindmapPlatformCaseMap = new Map(tree.platformCases.map(pc => [pc.id, pc]));
  ensureMindmapNavSelection(tree);
  renderMindmapNav(tree.roots, document.getElementById('mindmapNavSearch')?.value);
  renderMindmapDetail(tree);
  if (mindmapSubView === 'tree') renderMindmapTreeOverview(tree);
}


function escapeHtml(s) {
  return (s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function downloadTextFile(filename, content, mime) {
  const blob = new Blob([content], { type: mime || 'text/plain;charset=utf-8' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  URL.revokeObjectURL(a.href);
}

let resultView = 'table'; // table | duplicate | mindmap

function setResultView(view) {
  if (view === 'duplicate' && !hasDuplicateSuspects()) view = 'table';
  if (view === 'mindmap' && analysisMode !== 'mindmap') view = 'table';
  resultView = view;

  const tablePanel = document.getElementById('tablePanel');
  const duplicatePanel = document.getElementById('duplicatePanel');
  const mindmapPanel = document.getElementById('mindmapPanel');
  const filterBar = document.getElementById('filterBar');
  const tabTable = document.getElementById('viewTabTable');
  const tabDuplicate = document.getElementById('viewTabDuplicate');
  const tabMindmap = document.getElementById('viewTabMindmap');

  const isTable = view === 'table';
  const isDuplicate = view === 'duplicate';
  const isMindmap = view === 'mindmap';

  if (tablePanel) tablePanel.style.display = isTable ? '' : 'none';
  if (duplicatePanel) duplicatePanel.classList.toggle('visible', isDuplicate);
  if (mindmapPanel) mindmapPanel.classList.toggle('visible', isMindmap);
  if (filterBar) filterBar.style.display = isTable ? '' : 'none';

  tabTable?.classList.toggle('active', isTable);
  tabDuplicate?.classList.toggle('active', isDuplicate);
  tabMindmap?.classList.toggle('active', isMindmap);

  if (isDuplicate) renderDuplicateTable();
  if (isMindmap) refreshMindmapResultView();
}

function updateResultViewTabs() {
  const tabsEl = document.getElementById('resultViewTabs');
  const dupTab = document.getElementById('viewTabDuplicate');
  const mindTab = document.getElementById('viewTabMindmap');
  const showDup = hasDuplicateSuspects();
  const showMindmap = analysisMode === 'mindmap';
  const dupCount = currentCases.filter(c => c._dupSuspect).length;
  const groupCount = new Set(currentCases.filter(c => c._dupGroup).map(c => c._dupGroup)).size;

  if (tabsEl) tabsEl.style.display = (showDup || showMindmap || currentCases.length > 0) ? '' : 'none';
  if (dupTab) {
    dupTab.style.display = showDup ? '' : 'none';
    dupTab.textContent = showDup ? `🔍 重複比對 (${dupCount})` : '🔍 重複比對';
    dupTab.title = showDup ? `${groupCount} 組疑似重複、${dupCount} 筆案例` : '';
  }
  if (mindTab) mindTab.style.display = showMindmap ? '' : 'none';

  if (resultView === 'duplicate' && !showDup) setResultView('table');
  else if (resultView === 'mindmap' && !showMindmap) setResultView('table');
}

function updateMindmapBreakdown(tree) {
  const el = document.getElementById('caseBreakdown');
  if (!el) return;
  el.innerHTML = tree.modules.map(m =>
    `${escapeHtml(m.name)} <strong>${m.platformCaseCount ?? m.caseCount}</strong> 卡`
  ).join(' · ');
}

function applyMindmapResultChrome(tree, validCount, skippedCount) {
  document.querySelector('.result-header .card-title').textContent = '✅ 心智圖產出完成';
  document.getElementById('caseCount').textContent =
    `${tree.platformCaseCount ?? validCount} 卡（${validCount} 列）`;
  const warn = document.getElementById('emptyWarn');
  if (skippedCount > 0) {
    warn.style.display = '';
    warn.textContent = `（已略過 ${skippedCount} 筆非有效案例）`;
  } else {
    warn.style.display = 'none';
    warn.textContent = '';
  }
  updateMindmapBreakdown(tree);
  document.getElementById('exportCsvBtn').style.display = 'none';
  document.getElementById('exportMindmapBtn').style.display = '';
  document.getElementById('removeObsoleteBtn').style.display = 'none';
  document.getElementById('refillBtn').style.display = 'none';
  document.querySelector('.priority-legend')?.style.setProperty('display', 'none');
  updateResultViewTabs();
}

function applyMindmapResultUi(tree, validCount, skippedCount) {
  applyMindmapResultChrome(tree, validCount, skippedCount);
  setResultView('mindmap');
}

function stashMindmapSession() {
  if (!lastMindmapExport?.tree) return;
  mindmapSessionCache = {
    export: lastMindmapExport,
    navSelection: mindmapNavSelection ? [...mindmapNavSelection] : null,
    subView: mindmapSubView,
    collapsedCards: [...mindmapCollapsedCards],
    resultView: resultView === 'mindmap' ? 'mindmap' : 'table',
  };
}

function restoreMindmapSessionFromCache() {
  if (!mindmapSessionCache?.export?.tree) return false;
  lastMindmapExport = mindmapSessionCache.export;
  mindmapNavSelection = mindmapSessionCache.navSelection
    ? [...mindmapSessionCache.navSelection]
    : null;
  mindmapSubView = mindmapSessionCache.subView || 'browse';
  mindmapCollapsedCards = new Set(mindmapSessionCache.collapsedCards || []);
  return true;
}

/** 還原一般分析結果區按鈕／圖例；可選擇是否清 DOM 與樹資料 */
function restoreStandardResultChrome({ clearMindmapExport = false, clearMindmapDom = false } = {}) {
  const exportBtn = document.getElementById('exportCsvBtn');
  if (exportBtn) exportBtn.style.display = '';
  const mindmapExportBtn = document.getElementById('exportMindmapBtn');
  if (mindmapExportBtn) mindmapExportBtn.style.display = 'none';
  document.querySelector('.priority-legend')?.style.setProperty('display', '');

  if (clearMindmapDom) {
    document.getElementById('mindmapNavTree') && (document.getElementById('mindmapNavTree').innerHTML = '');
    document.getElementById('mindmapDetailCards') && (document.getElementById('mindmapDetailCards').innerHTML = '');
    document.getElementById('mindmapTreeView') && (document.getElementById('mindmapTreeView').innerHTML = '');
    mindmapNavSelection = null;
    mindmapPlatformCaseMap = new Map();
    mindmapCollapsedCards = new Set();
    setMindmapLoadingOverlay(false);
  }

  if (clearMindmapExport) {
    lastMindmapExport = null;
    mindmapSessionCache = null;
  }
}

/** 離開心智圖模式：保留樹資料，強制顯示案例表格 */
function leaveMindmapMode() {
  stashMindmapSession();
  restoreStandardResultChrome({ clearMindmapExport: false, clearMindmapDom: true });
  setResultView('table');
  const titleEl = document.querySelector('.result-header .card-title');
  if (titleEl && !lastAnalysisWasModularize) {
    titleEl.textContent = '✅ 產出完成';
  }
  updateResultViewTabs();
}

/** 進入心智圖模式：從快取還原樹並重繪 */
function enterMindmapMode() {
  if (!lastMindmapExport?.tree) restoreMindmapSessionFromCache();
  if (!lastMindmapExport?.tree && currentCases.length) syncMindmapExportFromCases();
  if (!lastMindmapExport?.tree) return;

  applyMindmapResultChrome(
    lastMindmapExport.tree,
    lastMindmapExport.validCount,
    lastMindmapExport.skippedCount
  );

  const wantMindmapView =
    mindmapSessionCache?.resultView === 'mindmap' || resultView === 'mindmap';
  if (wantMindmapView) setResultView('mindmap');
}

/** 還原一般分析結果區 UI（非心智圖模式，含清除樹資料） */
function restoreStandardResultUi() {
  restoreStandardResultChrome({ clearMindmapExport: true, clearMindmapDom: true });
  if (resultView === 'mindmap') setResultView('table');
  updateResultViewTabs();
}

function resetMindmapResultUi() {
  restoreStandardResultUi();
  const titleEl = document.querySelector('.result-header .card-title');
  if (titleEl && !lastAnalysisWasModularize) {
    titleEl.textContent = '✅ 產出完成';
  }
}

function setMindmapLoadingOverlay(show, text, sub) {
  const overlay = document.getElementById('mindmapLoadingOverlay');
  const textEl = document.getElementById('mindmapLoadingText');
  const subEl = document.getElementById('mindmapLoadingSub');
  if (!overlay) return;
  overlay.classList.toggle('visible', !!show);
  overlay.setAttribute('aria-hidden', show ? 'false' : 'true');
  if (text && textEl) textEl.textContent = text;
  if (sub && subEl) subEl.textContent = sub;
}

async function runMindmapFromXlsx() {
  const file = document.getElementById('mindmapFile')?.files?.[0];
  if (!file) {
    showError('請上傳 TestCase 檔案（CSV / XLSX）');
    return;
  }

  const resultSection = document.getElementById('resultSection');
  const isRerun = !!lastMindmapExport && resultSection?.classList.contains('visible');

  document.getElementById('statusPanel').classList.add('visible');
  if (isRerun) {
    setMindmapLoadingOverlay(true, '重新產生平台樹狀圖…', `讀取 ${file.name}`);
    resultSection?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  } else {
    setMindmapLoadingOverlay(false);
    resultSection?.classList.remove('visible');
  }
  mindmapNavSelection = null;
  clearResultFilters();
  document.getElementById('analyzeBtn').disabled = true;
  document.getElementById('stepV').style.display = 'none';
  document.getElementById('aiProgressWrap').style.display = 'none';
  lastAnalysisWasModularize = false;
  lastModularizeResult = null;
  toggleModularizeTableColumns(false);

  try {
    setStep(1, 'running');
    document.getElementById('step1Text').textContent = '讀取 TestCase 檔案...';
    if (isRerun) setMindmapLoadingOverlay(true, '讀取 TestCase 檔案…', file.name);
    const raw = await loadBaselineCasesFromFile(file);
    const cases = raw.map(r => normalizeCaseEntry(r, null));
    setStep(1, 'done');
    document.getElementById('step1Text').textContent =
      `已載入 ${file.name}（共 ${cases.length} 筆）`;

    setStep(2, 'running');
    document.getElementById('step2Text').textContent = '組織主模組與功能樹狀結構...';
    if (isRerun) setMindmapLoadingOverlay(true, '合併平台案例卡…', `共 ${cases.length} 列`);
    const tree = buildMindMapTree(cases, { indexNames: getModuleIndexFilenames() });
    currentCases = cases.filter(isMindmapCaseValid);
    coverageInspectCases = null;
    assignMindmapExport(tree, currentCases.length);
    setStep(2, 'done');
    document.getElementById('step2Text').textContent =
      `合併 ${tree.platformCaseCount} 張平台案例卡（原始 ${tree.validCount} 列，略過 ${tree.skippedCount} 筆）`;

    setStep(3, 'running');
    document.getElementById('step3Text').textContent = '渲染目錄瀏覽與樹狀總覽...';
    if (isRerun) setMindmapLoadingOverlay(true, '渲染目錄與案例卡…', `${tree.platformCaseCount} 張案例卡`);
    renderTable(currentCases, cases);
    mindmapNavSelection = tree.roots[0] ? [tree.roots[0].name] : null;
    mindmapSubView = 'browse';
    applyMindmapResultUi(tree, tree.validCount, tree.skippedCount);
    setStep(3, 'done');
    document.getElementById('step3Text').textContent = '完成';

    document.getElementById('resultSection').classList.add('visible');
  } catch (err) {
    showError(err.message || String(err));
    setStep(1, 'error');
    if (!lastMindmapExport) resultSection?.classList.remove('visible');
  } finally {
    setMindmapLoadingOverlay(false);
    document.getElementById('analyzeBtn').disabled = false;
    checkReady();
  }
}

// ─── 多批模組化 ──────────────────────────────────────────────
const MOD_CAT_SLUG = {
  '平台': 'PLT', '大廳': 'LOB', '房內': 'ROM', '異常處理': 'EXC', '後台': 'BKG'
};

let lastModularizeResult = null; // { masters, classifications, summary }
let lastAnalysisWasModularize = false;

function normalizeMatchText(text) {
  return (text || '')
    .toString()
    .toLowerCase()
    .replace(/\s+/g, '')
    .replace(/[，。、；；：:「」[\]()（）"'<>]/g, '')
    .trim();
}

function isNavigationEntryCase(c) {
  const blob = `${c['功能頁面/元件'] || ''} ${c['測試標題'] || ''}`.toLowerCase();
  const navHint = /入口|導覽|navigation|跳轉|導航|導向|icon|圖示/.test(blob);
  const editHint = /編輯|儲存|required|invalid|format|confirm|欄位|驗證|otp|密碼|email|nickname/.test(blob);
  return navHint && !editHint;
}

/** 測試類型縮寫（分群用） */
function normalizeTestTypeKind(raw) {
  const s = (raw || '').trim();
  if (s.includes('正面')) return 'POS';
  if (s.includes('負面')) return 'NEG';
  if (s.includes('邊界')) return 'BND';
  if (s.includes('後台')) return 'ADM';
  if (s.includes('異常')) return 'EXC';
  return normalizeMatchText(s).slice(0, 6).toUpperCase() || 'UNK';
}

/** 從標題推斷驗證欄位／對象 */
function inferValidationField(c) {
  const title = `${c['測試標題'] || ''} ${c['前置條件'] || ''}`.toLowerCase();
  if (/email|信箱|郵箱|e-mail/.test(title)) return 'EMAIL';
  if (/otp|驗證碼|verification\s*code/.test(title)) return 'OTP';
  if (/first\s*name|firstname/.test(title)) return 'FNAME';
  if (/last\s*name|lastname/.test(title)) return 'LNAME';
  if (/middle\s*name/.test(title)) return 'MNAME';
  if (/nickname|暱稱/.test(title)) return 'NICK';
  if (/wallet|錢包/.test(title) && /密碼|password/.test(title)) return 'WPWD';
  if (/password|密碼/.test(title)) return 'PWD';
  if (/birthday|生日|滿21|21\+/.test(title)) return 'BDAY';
  if (/phone|電話|手機/.test(title)) return 'PHONE';
  if (/姓名/.test(title)) return 'NAME';
  return 'FIELD';
}

/** 抽出預期結果中的提示訊息（中英） */
function extractQuotedMessage(expected) {
  const s = (expected || '').toString();
  const patterns = [
    /[「『]([^」』]+)[」』]/,
    /['"]([^'"]{3,80})['"]/,
    /(?:提示|顯示|彈出|出現)[：:]?\s*([A-Za-z][A-Za-z0-9 .!?'<>\/\-]{2,60})/i
  ];
  for (const re of patterns) {
    const m = s.match(re);
    if (m && m[1]) return m[1].trim();
  }
  return '';
}

function canonicalizeRuleMessage(msg) {
  return normalizeMatchText(msg)
    .replace(/[!．.]+$/g, '')
    .replace(/<br\s*\/?>/g, '');
}

/**
 * 規則族比對鍵：測試類型 + 驗證規則（非整段預期結果逐字比對）
 * 例：NEG + EMAIL + REQUIRED 可跨「存款補全」與「個人資料」合併
 */
function extractRuleFamilyKey(c) {
  const kind = normalizeTestTypeKind(c['測試類型']);
  const field = inferValidationField(c);
  const expRaw = (c['預期結果'] || '').trim();
  const titleRaw = (c['測試標題'] || '').trim();
  const blob = canonicalizeRuleMessage(`${expRaw} ${extractQuotedMessage(expRaw)} ${titleRaw}`);

  const rules = [
    { re: /emailisinus|email.*inuse|已被其他帳號|已被.*使用|inuse/, rule: 'IN_USE', field: 'EMAIL' },
    { re: /invalidemail|invalidemailformat|emailformat|無效.*email|email.*格式/, rule: 'INVALID', field: 'EMAIL' },
    { re: /passworddonotmatch|密碼.*不一致|donotmatch/, rule: 'MISMATCH', field: 'PWD' },
    { re: /invalidpassword|passwordformat|密碼格式|invalidverification|invalidverificationcode/, rule: 'INVALID', field: 'PWD' },
    { re: /invalidverification|verificationcode|otp.*invalid|驗證碼.*錯/, rule: 'INVALID', field: 'OTP' },
    { re: /toomanyattempts|too\s*many|過多.*嘗試|請.*分鐘|10:00/, rule: 'LOCKOUT', field: 'OTP' },
    { re: /unsavedchange|未儲存.*離開|willbelost|doyouwanttocontinue/, rule: 'UNSAVED_LEAVE', field: 'FORM' },
    { re: /mustbe21|未滿21|21\+/, rule: 'AGE_MIN', field: 'BDAY' },
    { re: /wrongformat|格式錯誤|姓名格式/, rule: 'FORMAT', field: field === 'FIELD' ? 'NAME' : field },
    { re: /max30|超過30|30characters/, rule: 'MAX_LEN', field: 'NICK' },
    { re: /nicknamechanges|24hours|24小時|onceevery/, rule: 'RATE_LIMIT', field: 'NICK' },
    { re: /required|必填|請填/, rule: 'REQUIRED', field },
    { re: /saved!|顯示輕提示.*saved/, rule: 'SAVE_OK' }
  ];

  for (const { re, rule, field: forcedField } of rules) {
    if (re.test(blob)) {
      const f = forcedField || field;
      return `${kind}::${f}::${rule}`;
    }
  }

  const quoted = extractQuotedMessage(expRaw);
  if (quoted) {
    const msgKey = canonicalizeRuleMessage(quoted).slice(0, 48);
    if (msgKey.length >= 4) return `${kind}::${field}::MSG::${msgKey}`;
  }

  const rawExp = canonicalizeRuleMessage(expRaw).slice(0, 48);
  if (rawExp.length >= 6) return `${kind}::${field}::RAW::${rawExp}`;

  const titleKey = canonicalizeRuleMessage(titleRaw).slice(0, 40);
  return `${kind}::${field}::TITLE::${titleKey || 'EMPTY'}`;
}

function caseMatchSignature(c) {
  return extractRuleFamilyKey(c);
}

function ruleFamilySlug(ruleKey) {
  return (ruleKey || '')
    .split('::')
    .filter(p => !['POS', 'NEG', 'BND', 'ADM', 'EXC', 'UNK'].includes(p))
    .join('_')
    .replace(/[^A-Z0-9_]/gi, '')
    .slice(0, 24) || 'RULE';
}

function buildModuleId(repCase, seq, isCore, ruleKey) {
  const cat = MOD_CAT_SLUG[repCase['類別']] || 'GEN';
  const kw = ruleFamilySlug(ruleKey || extractRuleFamilyKey(repCase));
  const tier = isCore ? 'CORE' : 'SUB';
  return `MOD_${cat}_${kw}_${tier}_${String(seq).padStart(3, '0')}`;
}

function formatCommonClass(batchSet) {
  const arr = ['A', 'B', 'C'].filter(b => batchSet.has(b));
  if (arr.length >= 3) return '共同-ABC';
  if (arr.length === 2) return `共同-${arr.join('')}`;
  return `${arr[0] || '?'}-only`;
}

function isAmbiguousCluster(members) {
  if (members.length < 2) return false;
  const navFlags = new Set(members.map(m => isNavigationEntryCase(m.case)));
  if (navFlags.size > 1) return true;
  const feats = new Set(members.map(m => normalizeMatchText(m.case['功能頁面/元件'])));
  if (feats.size > 2) return true;
  return false;
}

function clusterModularizeCases(batchLists) {
  const batchLabels = batchLists.map((_, i) => ['A', 'B', 'C'][i]);
  const clusterMap = new Map();

  batchLists.forEach((rows, bi) => {
    const batch = batchLabels[bi];
    rows.forEach(c => {
      const nav = isNavigationEntryCase(c);
      const sig = extractRuleFamilyKey(c);
      const clusterKey = `${sig}::${nav ? 'nav' : 'page'}`;
      if (!clusterMap.has(clusterKey)) clusterMap.set(clusterKey, []);
      clusterMap.get(clusterKey).push({ batch, case: c, sig, nav });
    });
  });

  const clusters = [...clusterMap.entries()].map(([key, members]) => ({ key, members }));
  return rebuildModularizeFromClusters(clusters);
}

function rebuildModularizeFromClusters(clusters) {
  const masters = [];
  const classifications = [];
  let modSeq = 1;
  const summary = {
    total: 0,
    core: 0,
    pair: 0,
    onlyA: 0,
    onlyB: 0,
    onlyC: 0
  };

  for (const { members } of clusters) {
    const batchSet = new Set(members.map(m => m.batch));
    const batchCount = batchSet.size;
    const rep = members[0].case;
    let modClass;
    let moduleId = '';

    if (batchCount >= 2) {
      const isCore = batchCount >= 3;
      const ruleKey = members[0].sig;
      moduleId = buildModuleId(rep, modSeq++, isCore, ruleKey);
      modClass = formatCommonClass(batchSet);
      const scenes = [...new Set(members.map(m => (m.case['功能頁面/元件'] || '').trim()).filter(Boolean))];
      masters.push({
        '模組編號': moduleId,
        '模組層級': isCore ? '核心模組' : '子模組',
        '規則族': ruleKey,
        '適用批次': [...batchSet].sort().join(','),
        '測試類型': rep['測試類型'] || '',
        '類別': rep['類別'] || '',
        '優先度': rep['優先度'] || '',
        '測試標題': rep['測試標題'] || '',
        '預期結果': rep['預期結果'] || '',
        '適用場景': scenes.join(' | '),
        '原編號清單': members.map(m => `${m.batch}:${m.case['編號'] || ''}`).join('; '),
        '比對鍵': ruleKey
      });
      if (isCore) summary.core++;
      else summary.pair++;
    } else {
      const only = [...batchSet][0];
      modClass = `${only}-only`;
      if (only === 'A') summary.onlyA++;
      else if (only === 'B') summary.onlyB++;
      else summary.onlyC++;
    }

    for (const m of members) {
      classifications.push({
        ...m.case,
        '狀態': m.case['狀態'] || '有效',
        '取代者': m.case['取代者'] || '',
        '來源批次': m.batch,
        '分類': modClass,
        '建議模組編號': moduleId,
        _modClass: modClass,
        _modModule: moduleId,
        _modBatch: m.batch
      });
      summary.total++;
    }
  }

  return { masters, classifications, summary, clusters };
}

function splitClustersByAiReject(clusterResult, aiMap) {
  const rejectKeys = new Set(
    [...aiMap.entries()].filter(([, same]) => same === false).map(([k]) => k)
  );
  if (!rejectKeys.size) return clusterResult;

  const split = [];
  for (const cl of clusterResult.clusters) {
    if (rejectKeys.has(cl.key) && cl.members.length > 1) {
      for (const m of cl.members) {
        split.push({ key: `${cl.key}::${m.batch}::${m.case['編號']}`, members: [m] });
      }
    } else {
      split.push(cl);
    }
  }
  return rebuildModularizeFromClusters(split);
}


async function confirmAmbiguousClustersWithAi(apiKey, clusters) {
  const ambiguous = clusters.filter(c => isAmbiguousCluster(c.members));
  if (!ambiguous.length) return new Map();

  const payload = ambiguous.map(c => ({
    clusterKey: c.key,
    cases: c.members.map(m => ({
      batch: m.batch,
      編號: m.case['編號'],
      功能頁面: m.case['功能頁面/元件'],
      測試標題: m.case['測試標題'],
      預期結果: m.case['預期結果']
    }))
  }));

  const raw = await callLlm(getLlmProvider(), apiKey, PROMPT_MODULAR_CONFIRM(JSON.stringify(payload, null, 2)), getSelectedModelId());
  const parsed = parseAiJson(raw);
  const map = new Map();
  (Array.isArray(parsed) ? parsed : []).forEach(row => {
    if (row && row.clusterKey != null) map.set(row.clusterKey, !!row.sameModule);
  });
  return map;
}

function toggleModularizeTableColumns(show) {
  ['thModBatch', 'thModClass', 'thModModule'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.style.display = show ? '' : 'none';
  });
  lastAnalysisWasModularize = !!show;
}

function updateModularizeBreakdown(summary) {
  const el = document.getElementById('caseBreakdown');
  if (!el || !summary) return;
  el.innerHTML = `
    模組 <strong style="color:var(--blue)">${summary.core + summary.pair}</strong> 個
    （核心 ${summary.core}、子模組 ${summary.pair}）
    · A-only <strong>${summary.onlyA}</strong>
    · B-only <strong>${summary.onlyB}</strong>
    ${summary.onlyC ? `· C-only <strong>${summary.onlyC}</strong>` : ''}
  `;
}

async function downloadModularizeXLSX(result) {
  const wb = new ExcelJS.Workbook();
  wb.creator = 'TestCaseGenerator';

  const styleHeader = (ws) => {
    ws.getRow(1).eachCell(cell => {
      cell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FF1E3A5F' } };
      cell.font = { bold: true, color: { argb: 'FF74C0FC' }, size: 11 };
    });
    ws.getRow(1).height = 22;
  };

  const wsMaster = wb.addWorksheet('模組母版', { views: [{ state: 'frozen', ySplit: 1 }] });
  wsMaster.columns = [
    { header: '模組編號', key: 'id', width: 28 },
    { header: '模組層級', key: 'tier', width: 12 },
    { header: '規則族', key: 'rule', width: 36 },
    { header: '適用批次', key: 'batches', width: 12 },
    { header: '測試類型', key: 'type', width: 10 },
    { header: '類別', key: 'cat', width: 10 },
    { header: '優先度', key: 'prio', width: 8 },
    { header: '測試標題', key: 'title', width: 45 },
    { header: '預期結果', key: 'exp', width: 35 },
    { header: '適用場景', key: 'scenes', width: 40 },
    { header: '原編號清單', key: 'orig', width: 50 },
    { header: '比對鍵', key: 'key', width: 36 }
  ];
  styleHeader(wsMaster);
  (result.masters || []).forEach(m => {
    wsMaster.addRow({
      id: m['模組編號'],
      tier: m['模組層級'],
      rule: m['規則族'] || m['比對鍵'],
      batches: m['適用批次'],
      type: m['測試類型'],
      cat: m['類別'],
      prio: m['優先度'],
      title: m['測試標題'],
      exp: m['預期結果'],
      scenes: m['適用場景'],
      orig: m['原編號清單'],
      key: m['比對鍵']
    }).alignment = { wrapText: true, vertical: 'top' };
  });

  const wsClass = wb.addWorksheet('分類清單', { views: [{ state: 'frozen', ySplit: 1 }] });
  wsClass.columns = [
    { header: '來源批次', key: 'batch', width: 8 },
    { header: '分類', key: 'cls', width: 14 },
    { header: '建議模組編號', key: 'mod', width: 28 },
    { header: '編號', key: 'id', width: 20 },
    { header: '測試類型', key: 'type', width: 10 },
    { header: '類別', key: 'cat', width: 10 },
    { header: '優先度', key: 'prio', width: 8 },
    { header: '主模組', key: 'main', width: 14 },
    { header: '層級', key: 'tier', width: 6 },
    { header: '功能頁面/元件', key: 'feat', width: 28 },
    { header: '測試標題', key: 'title', width: 45 },
    { header: '預期結果', key: 'exp', width: 35 },
    { header: '規格來源', key: 'src', width: 16 },
    { header: '版本標籤', key: 'ver', width: 14 }
  ];
  styleHeader(wsClass);
  (result.classifications || []).forEach(c => {
    wsClass.addRow({
      batch: c['來源批次'],
      cls: c['分類'],
      mod: c['建議模組編號'] || '',
      id: c['編號'],
      type: c['測試類型'],
      cat: c['類別'],
      prio: c['優先度'],
      main: c['主模組'],
      tier: c['層級'],
      feat: c['功能頁面/元件'],
      title: c['測試標題'],
      exp: c['預期結果'],
      src: c['規格來源'],
      ver: c['版本標籤']
    }).alignment = { wrapText: true, vertical: 'top' };
  });

  const wsSum = wb.addWorksheet('摘要');
  wsSum.addRow(['項目', '數量']);
  const s = result.summary || {};
  [
    ['案例總數', s.total],
    ['核心模組 (ABC)', s.core],
    ['子模組 (AB/BC/CA)', s.pair],
    ['A-only', s.onlyA],
    ['B-only', s.onlyB],
    ['C-only', s.onlyC || 0],
    ['模組母版數', (result.masters || []).length]
  ].forEach(([k, v]) => wsSum.addRow([k, v]));

  const buffer = await wb.xlsx.writeBuffer();
  const blob = new Blob([buffer], {
    type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
  });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `test_cases_modularize_${getTodayStr()}.xlsx`;
  a.click();
  URL.revokeObjectURL(a.href);
}

async function runModularizeAnalysis() {
  clearError();
  const apiKey = document.getElementById('apiKeyInput').value.trim();
  const useAi = document.getElementById('modUseAiConfirm')?.checked;
  const fileA = document.getElementById('batchFileA')?.files?.[0];
  const fileB = document.getElementById('batchFileB')?.files?.[0];
  const fileC = document.getElementById('batchFileC')?.files?.[0];

  if (!fileA || !fileB) {
    showError('請上傳至少批次 A 與批次 B（CSV / XLSX）');
    return;
  }
  if (useAi && !apiKey) {
    showError(`已勾選 AI 確認，請填入 ${getApiKeyLabel()}`);
    return;
  }

  if (currentCases.length > 0) {
    const choice = await promptAppendOrReplace();
    if (choice === 'replace') currentCases = [];
  }

  document.getElementById('statusPanel').classList.add('visible');
  document.getElementById('resultSection').classList.remove('visible');
  document.getElementById('analyzeBtn').disabled = true;
  document.getElementById('stepV').style.display = 'none';

  try {
    setStep(1, 'running');
    document.getElementById('step1Text').textContent = '載入批次 TestCase...';

    const batchMeta = [
      { file: fileA, label: 'A' },
      { file: fileB, label: 'B' }
    ];
    if (fileC) batchMeta.push({ file: fileC, label: 'C' });

    const batchLists = [];
    for (const { file, label } of batchMeta) {
      const rows = await loadBaselineCasesFromFile(file);
      batchLists.push(rows);
    }

    setStep(1, 'done');
    document.getElementById('step1Text').textContent =
      `已載入 ${batchMeta.map(b => `${b.label}:${b.file.name}`).join('、')}`;

    setStep(2, 'running');
    document.getElementById('step2Text').textContent = '比對相同規則並分群...';

    let clusterResult = clusterModularizeCases(batchLists);

    if (useAi) {
      document.getElementById('step2Text').textContent = '程式分群完成，AI 確認疑似群組...';
      const aiMap = await confirmAmbiguousClustersWithAi(apiKey, clusterResult.clusters);
      clusterResult = splitClustersByAiReject(clusterResult, aiMap);
    }

    setStep(2, 'done');
    document.getElementById('step2Text').textContent =
      useAi ? '分群與 AI 確認完成' : '程式分群完成';

    setStep(3, 'running');
    document.getElementById('step3Text').textContent = '產出模組母版與分類清單...';

    lastModularizeResult = clusterResult;
    currentCases = clusterResult.classifications;
    toggleModularizeTableColumns(true);
    updateModularizeBreakdown(clusterResult.summary);

    setStep(3, 'done');
    document.getElementById('step3Text').textContent =
      `完成：母版 ${clusterResult.masters.length} 個，分類 ${clusterResult.classifications.length} 筆（原編號未改）`;

    restoreStandardResultUi();
    document.getElementById('resultSection').classList.add('visible');
    document.querySelector('.result-header .card-title').textContent = '✅ 模組化分析完成';
    document.getElementById('exportCsvBtn').textContent = '📊 匯出模組化報表';
    refreshDisplay();

  } catch (err) {
    const step = [1, 2, 3].find(n =>
      document.getElementById(`step${n}Icon`).classList.contains('running')
    ) || 1;
    setStep(step, 'error');
    showApiError(err);
  } finally {
    document.getElementById('analyzeBtn').disabled = false;
    checkReady();
  }
}

// ─── UI 狀態管理 ─────────────────────────────────────────────
function setStep(n, status) {
  const icon = document.getElementById(`step${n}Icon`);
  const text = document.getElementById(`step${n}Text`);
  icon.className = `step-icon ${status}`;
  text.className = `step-text ${status === 'running' ? 'active' : 'muted'}`;
  if (status === 'done') icon.textContent = '✓';
  else if (status === 'error') icon.textContent = '✗';
  else icon.textContent = String(n);
}

function showError(msg) {
  const box = document.getElementById('errorBox');
  box.textContent = '❌ ' + msg;
  box.classList.add('visible');
}

function showApiError(err) {
  showError(formatApiError(err, { provider: getProviderLabel() }));
}

/** 多規格分批之間節流，降低 Gemini RPM 超限 */
async function throttleBetweenBatches(batchLabel) {
  const sec = Math.round(MULTI_BATCH_THROTTLE_MS / 1000);
  const step2 = document.getElementById('step2Text');
  if (step2) {
    step2.textContent = `${batchLabel}：等待 ${sec} 秒（避免 API 額度限制）…`;
  }
  await llmSleep(MULTI_BATCH_THROTTLE_MS);
}

function clearError() {
  document.getElementById('errorBox').classList.remove('visible');
}

// ─── 表格渲染 ────────────────────────────────────────────────
function typeTag(v) {
  if (!v) return '';
  if (v.includes('正面')) return `<span class="tag tag-pos">正面</span>`;
  if (v.includes('負面')) return `<span class="tag tag-neg">負面</span>`;
  if (v.includes('邊界')) return `<span class="tag tag-bnd">邊界</span>`;
  return `<span class="tag">${v}</span>`;
}
function catTag(v) {
  if (!v) return '';
  if (v.includes('平台'))   return `<span class="tag tag-plt">平台</span>`;
  if (v.includes('大廳'))   return `<span class="tag tag-hall">大廳</span>`;
  if (v.includes('房內'))   return `<span class="tag tag-room">房內</span>`;
  if (v.includes('異常'))   return `<span class="tag tag-err">異常</span>`;
  if (v.includes('後台'))   return `<span class="tag tag-admin">後台</span>`;
  return `<span class="tag">${v}</span>`;
}
function tierTag(v) {
  if (!v) return '';
  const u = v.toUpperCase();
  if (u === 'L1') return `<span class="tag tag-l1">L1</span>`;
  if (u === 'L2') return `<span class="tag tag-l2">L2</span>`;
  if (u === 'L3') return `<span class="tag tag-l3">L3</span>`;
  return `<span class="tag">${v}</span>`;
}
function lvlTag(v) {
  if (!v) return '';
  if (v.includes('P0')) return `<span class="tag tag-p0">P0</span>`;
  if (v.includes('P1')) return `<span class="tag tag-p1">P1</span>`;
  if (v.includes('P2')) return `<span class="tag tag-p2">P2</span>`;
  return `<span class="tag">${v}</span>`;
}

function cellOrEmpty(val, extraClass = '', suspicious = false) {
  if (!val || val.trim() === '') {
    return `<td class="cell-empty ${extraClass}" title="AI 未產出此欄位">—</td>`;
  }
  if (suspicious) {
    return `<td class="cell-suspicious ${extraClass}" title="可疑：可能引用了指令編號而非規格書章節">${val}</td>`;
  }
  return `<td class="${extraClass}">${val}</td>`;
}

const EMPTY_CHECK_FIELDS = ['主模組', '功能頁面/元件', '測試標題', '預期結果', '規格來源'];

// ─── 跳轉到指定案例列 ─────────────────────────────────────────
function scrollToCase(caseId) {
  const row = document.querySelector(`tr[data-case-id="${CSS.escape(caseId)}"]`);
  if (!row) return;
  row.scrollIntoView({ behavior: 'smooth', block: 'center' });
  row.classList.remove('row-highlight');
  void row.offsetWidth; // 強制 reflow，確保動畫重播
  row.classList.add('row-highlight');
  row.addEventListener('animationend', () => row.classList.remove('row-highlight'), { once: true });
}

// renderTable(displayCases, allCases)
// displayCases：篩選後要渲染的列；allCases：完整資料（用於統計警告）
function renderTable(cases, allCases) {
  if (!allCases) allCases = cases;
  const tbody = document.getElementById('resultTbody');
  tbody.innerHTML = '';
  const emptyDetails = [];
  let obsoleteCount = 0;

  // 統計來自 allCases（完整資料）
  allCases.forEach(c => {
    const missingFields = EMPTY_CHECK_FIELDS.filter(f => !c[f] || c[f].trim() === '');
    if (missingFields.length > 0) {
      emptyDetails.push({ id: c['編號'] || '(無編號)', fields: missingFields });
    }
    if (c['_obsolete'] || c['狀態'] === '失效') obsoleteCount++;
  });

  // 渲染列（filtered+sorted cases）
  cases.forEach(c => {
    const isObsolete = !!c['_obsolete'] || c['狀態'] === '失效';

    const repCell = isObsolete
      ? ((c['_replacedBy'] || c['取代者'])
          ? `<td class="col-rep"><span class="case-link" onclick="scrollToCase('${c['_replacedBy'] || c['取代者']}')">${c['_replacedBy'] || c['取代者']}</span></td>`
          : `<td class="col-rep" style="color:var(--muted);font-size:11px;">已廢除</td>`)
      : `<td class="col-rep"></td>`;

    const tr = document.createElement('tr');
    if (isObsolete) tr.classList.add('row-obsolete');
    if (c._dupSuspect) tr.classList.add('row-dup-suspect');
    const caseId = c['編號'] || '';
    if (caseId) tr.setAttribute('data-case-id', caseId);
    const checked = caseId && selectedCaseIds.has(caseId) ? 'checked' : '';
    const modCols = lastAnalysisWasModularize
      ? `<td class="col-mod-batch">${c['_modBatch'] || c['來源批次'] || ''}</td>
         <td class="col-mod-class">${c['_modClass'] || c['分類'] || ''}</td>
         <td class="col-mod-module">${c['_modModule'] || c['建議模組編號'] || '—'}</td>`
      : '';
    tr.innerHTML = `
      ${modCols}
      <td class="col-check">${caseId ? `<input type="checkbox" class="case-select-cb" data-case-id="${caseId.replace(/"/g, '&quot;')}" ${checked} />` : ''}</td>
      <td class="col-status">${isObsolete ? '❌ 失效' : c._dupSuspect ? `⚠ 疑似重複${c._dupGroup ? `<br><span style="font-size:10px;color:var(--yellow)">${c._dupGroup}</span>` : ''}` : '✅ 有效'}</td>
      ${repCell}
      <td class="col-no">${c['編號'] || '<span class="cell-empty">—</span>'}</td>
      <td class="col-type">${typeTag(c['測試類型'])}</td>
      <td class="col-cat">${catTag(c['類別'])}</td>
      <td class="col-lvl">${lvlTag(c['優先度'])}</td>
      ${cellOrEmpty(c['主模組'], 'col-main')}
      <td class="col-tier">${tierTag(c['層級'])}</td>
      ${cellOrEmpty(c['功能頁面/元件'], 'col-feat')}
      ${cellOrEmpty(c['前置條件'], 'col-pre')}
      ${cellOrEmpty(c['測試標題'], 'col-title')}
      ${cellOrEmpty(c['預期結果'], 'col-exp')}
      ${cellOrEmpty(c['規格來源'], 'col-src', c['_srcSuspicious'])}
      <td class="col-ver">${c['版本標籤'] || ''}</td>
    `;
    tbody.appendChild(tr);
  });

  tbody.querySelectorAll('.case-select-cb').forEach(cb => {
    cb.addEventListener('change', () => {
      const id = cb.dataset.caseId;
      if (!id) return;
      if (cb.checked) selectedCaseIds.add(id);
      else selectedCaseIds.delete(id);
      updateDeleteSelectedBtn();
      syncSelectAllCheckbox();
      syncSelectAllDupCheckbox();
    });
  });

  if (analysisMode !== 'mindmap' || !lastMindmapExport?.tree) {
    document.getElementById('caseCount').textContent = allCases.length;
  }
  updateDeleteSelectedBtn();
  syncSelectAllCheckbox();

  // 移除失效按鈕
  const rmBtn = document.getElementById('removeObsoleteBtn');
  if (rmBtn) {
    if (obsoleteCount > 0) {
      rmBtn.textContent = `🗑 移除失效案例（${obsoleteCount} 筆）`;
      rmBtn.style.display = 'inline-flex';
    } else {
      rmBtn.style.display = 'none';
    }
  }

  // 空值警告 + 可點擊展開明細
  const warnEl   = document.getElementById('emptyWarn');
  const detailEl = document.getElementById('emptyWarnDetail');
  if (warnEl && detailEl) {
    if (emptyDetails.length > 0) {
      warnEl.textContent = `⚠ ${emptyDetails.length} 個案例含空值欄位 ▾`;
      warnEl.style.display = 'inline';
      const detailHtml = emptyDetails.map(d =>
        `<span class="case-link" onclick="scrollToCase('${d.id}')">${d.id}</span>：${d.fields.join('、')}`
      ).join('<br>');
      detailEl.innerHTML = detailHtml;
      detailEl.style.display = 'none';
      warnEl.onclick = () => {
        const open = detailEl.style.display !== 'none';
        detailEl.style.display = open ? 'none' : 'block';
        warnEl.textContent = `⚠ ${emptyDetails.length} 個案例含空值欄位 ${open ? '▾' : '▴'}`;
      };
    } else {
      warnEl.style.display  = 'none';
      detailEl.style.display = 'none';
    }
  }
}

function syncSelectAllDupCheckbox() {
  const selAll = document.getElementById('selectAllDup');
  if (!selAll) return;
  const ids = getDuplicateCases(currentCases).map(c => c['編號']).filter(Boolean);
  if (!ids.length) {
    selAll.checked = false;
    selAll.indeterminate = false;
    return;
  }
  const selectedCount = ids.filter(id => selectedCaseIds.has(id)).length;
  selAll.checked = selectedCount === ids.length;
  selAll.indeterminate = selectedCount > 0 && selectedCount < ids.length;
}

function renderDuplicateTable() {
  const tbody = document.getElementById('duplicateTbody');
  const emptyEl = document.getElementById('duplicateEmpty');
  const summaryEl = document.getElementById('duplicateSummary');
  if (!tbody) return;

  const dupCases = getDuplicateCases(currentCases);
  tbody.innerHTML = '';

  if (!dupCases.length) {
    if (emptyEl) emptyEl.style.display = '';
    if (summaryEl) summaryEl.textContent = '';
    updateDeleteSelectedBtn();
    syncSelectAllDupCheckbox();
    return;
  }
  if (emptyEl) emptyEl.style.display = 'none';

  const groups = new Map();
  dupCases.forEach(c => {
    if (!groups.has(c._dupGroup)) groups.set(c._dupGroup, []);
    groups.get(c._dupGroup).push(c);
  });

  if (summaryEl) {
    summaryEl.textContent =
      `共 ${groups.size} 組疑似重複、${dupCases.length} 筆案例。同組已排列在一起，請比對後勾選刪除多餘項。`;
  }

  [...groups.entries()]
    .sort((a, b) => a[0].localeCompare(b[0], undefined, { numeric: true }))
    .forEach(([gid, groupCases]) => {
      const first = groupCases[0];
      const feat = stripFeatureMarkers(first['功能頁面/元件'] || '') || '—';
      const rule = extractRuleFamilyKey(first);

      const headerTr = document.createElement('tr');
      headerTr.className = 'dup-group-header';
      headerTr.innerHTML =
        `<td colspan="7">${gid} · ${feat} · ${rule}（${groupCases.length} 筆）</td>`;
      tbody.appendChild(headerTr);

      groupCases.forEach(c => {
        const caseId = c['編號'] || '';
        const tr = document.createElement('tr');
        tr.classList.add('row-dup-suspect');
        if (caseId) tr.setAttribute('data-case-id', caseId);
        const checked = caseId && selectedCaseIds.has(caseId) ? 'checked' : '';
        tr.innerHTML = `
          <td class="col-check">${caseId ? `<input type="checkbox" class="dup-select-cb" data-case-id="${caseId.replace(/"/g, '&quot;')}" ${checked} />` : ''}</td>
          <td class="col-no">${caseId || '<span class="cell-empty">—</span>'}</td>
          ${cellOrEmpty(c['功能頁面/元件'], 'col-feat')}
          ${cellOrEmpty(c['測試標題'], 'col-title')}
          ${cellOrEmpty(c['預期結果'], 'col-exp')}
          ${cellOrEmpty(c['規格來源'], 'col-src', c['_srcSuspicious'])}
          <td class="col-lvl">${lvlTag(c['優先度'])}</td>
        `;
        tbody.appendChild(tr);
      });
    });

  tbody.querySelectorAll('.dup-select-cb').forEach(cb => {
    cb.addEventListener('change', () => {
      const id = cb.dataset.caseId;
      if (!id) return;
      if (cb.checked) selectedCaseIds.add(id);
      else selectedCaseIds.delete(id);
      updateDeleteSelectedBtn();
      syncSelectAllDupCheckbox();
      syncSelectAllCheckbox();
    });
  });

  updateDeleteSelectedBtn();
  syncSelectAllDupCheckbox();
}

// ─── 全域狀態 ────────────────────────────────────────────────
let currentCases      = [];
let sortState         = { col: null, dir: 'asc' };
let lastNewSpecText   = null;
let lastSpecOutline   = { mainOrder: [], items: [] };
let lastIndexOutline  = { mainOrder: [], items: [] };
let lastContentOutline = { mainOrder: [], items: [] };
let lastSpecSourceFilename = '';
/** 覆蓋率面板點 PRD 列時啟用（與搜尋框分開，用 caseMatchesDoc 比對） */
let filterPrdDoc = null;

function clearResultFilters() {
  filterPrdDoc = null;
  for (const id of ['filterText', 'filterType', 'filterCat', 'filterLevel', 'filterStatus']) {
    const el = document.getElementById(id);
    if (el) el.value = '';
  }
}

// ─── 篩選邏輯 ────────────────────────────────────────────────
function filterCases(cases) {
  const text   = (document.getElementById('filterText')?.value   || '').toLowerCase().trim();
  const type   =  document.getElementById('filterType')?.value   || '';
  const cat    =  document.getElementById('filterCat')?.value    || '';
  const level  =  document.getElementById('filterLevel')?.value  || '';
  const status =  document.getElementById('filterStatus')?.value || '';

  return cases.filter(c => {
    if (filterPrdDoc && !caseMatchesDoc(c['規格來源'], filterPrdDoc)) return false;
    if (type   && !(c['測試類型'] || '').includes(type))  return false;
    if (cat    && !(c['類別']     || '').includes(cat))   return false;
    if (level  && !(c['優先度'] || '').includes(level)) return false;
    if (status === 'valid'   &&  c['_obsolete'])  return false;
    if (status === 'obsolete' && !c['_obsolete']) return false;
    if (status === 'duplicate' && !c['_dupSuspect']) return false;
    if (text) {
      const haystack = [c['編號'], c['測試標題'], c['主模組'], c['功能頁面/元件'], c['預期結果'], c['規格來源'], c['類別'], c['分類'], c['建議模組編號'], c['_modBatch']]
        .map(v => v || '').join(' ').toLowerCase();
      if (!haystack.includes(text)) return false;
    }
    return true;
  });
}

// ─── 排序邏輯 ────────────────────────────────────────────────
function sortCases(cases) {
  if (!sortState.col) return sortCasesByOutline(cases, lastSpecOutline);
  const LVL_ORDER = { 'P0': 0, 'P1': 1, 'P2': 2 };
  return [...cases].sort((a, b) => {
    if (sortState.col === '優先度') {
      const va = LVL_ORDER[a['優先度']] ?? 9;
      const vb = LVL_ORDER[b['優先度']] ?? 9;
      return sortState.dir === 'asc' ? va - vb : vb - va;
    }
    const va = (a[sortState.col] || '').toString();
    const vb = (b[sortState.col] || '').toString();
    const cmp = va.localeCompare(vb, 'zh-TW', { numeric: true });
    return sortState.dir === 'asc' ? cmp : -cmp;
  });
}

// ─── 排序表頭 UI 更新 ────────────────────────────────────────
function updateSortHeaders() {
  document.querySelectorAll('th[data-sort-field]').forEach(th => {
    th.classList.remove('sort-asc', 'sort-desc');
    if (th.dataset.sortField === sortState.col) {
      th.classList.add(sortState.dir === 'asc' ? 'sort-asc' : 'sort-desc');
    }
  });
}

// ─── 案例數量細分 ────────────────────────────────────────────
function updateBreakdown() {
  const el     = document.getElementById('caseBreakdown');
  const legend = document.querySelector('.priority-legend');
  if (!el || currentCases.length === 0) {
    if (el)     el.textContent = '';
    if (legend) legend.classList.remove('visible');
    return;
  }
  if (legend) legend.classList.add('visible');
  let pos = 0, neg = 0, bnd = 0;
  currentCases.forEach(c => {
    const t = c['測試類型'] || '';
    if (t.includes('正面')) pos++;
    else if (t.includes('負面')) neg++;
    else if (t.includes('邊界')) bnd++;
  });
  el.innerHTML =
    `<span class="bd-pos">正面 ${pos}</span> ／ ` +
    `<span class="bd-neg">負面 ${neg}</span> ／ ` +
    `<span class="bd-bnd">邊界 ${bnd}</span>`;
}

// ─── 補填按鈕計數更新 ────────────────────────────────────────
function updateRefillBtn() {
  const btn = document.getElementById('refillBtn');
  if (!btn) return;
  const emptyCount = currentCases.filter(c =>
    EMPTY_CHECK_FIELDS.some(f => !c[f] || c[f].trim() === '')
  ).length;
  if (emptyCount > 0) {
    btn.textContent = `🔧 補填空值（${emptyCount} 筆）`;
    btn.style.display = '';
  } else {
    btn.style.display = 'none';
  }
}

// ─── 統一重繪（篩選 + 排序 + 存檔）────────────────────────────
function refreshDisplay() {
  if (analysisMode === 'mindmap') {
    if (currentCases.length) {
      const stale = !lastMindmapExport?.tree
        || lastMindmapExport.sourceCaseCount !== currentCases.length;
      if (stale) syncMindmapExportFromCases();
    }
    if (lastMindmapExport?.tree) {
      applyMindmapResultChrome(
        lastMindmapExport.tree,
        lastMindmapExport.validCount,
        lastMindmapExport.skippedCount
      );
    }
  } else {
    restoreStandardResultChrome({ clearMindmapExport: false, clearMindmapDom: false });
    const titleEl = document.querySelector('.result-header .card-title');
    if (titleEl && !lastAnalysisWasModularize) {
      titleEl.textContent = '✅ 產出完成';
    }
  }

  const filtered = filterCases(currentCases);
  const sorted   = sortCases(filtered);

  // 篩選計數提示
  const countEl = document.getElementById('filterCount');
  if (countEl) {
    if (filterPrdDoc) {
      countEl.textContent = `PRD：${filterPrdDoc}（${filtered.length} / ${currentCases.length} 筆）`;
    } else if (filtered.length < currentCases.length) {
      countEl.textContent = `篩選 ${filtered.length} / ${currentCases.length} 筆`;
    } else {
      countEl.textContent = '';
    }
  }

  renderTable(sorted, currentCases);   // 渲染已篩選列，統計來自全部
  if (analysisMode !== 'mindmap') updateBreakdown();
  updateRefillBtn();
  updateSortHeaders();
  checkReady();  // 更新前綴必填狀態
  updateResultViewTabs();
  setResultView(resultView);

  // 非同步自動儲存（fire & forget）
  if (currentCases.length > 0) dbSaveCases(currentCases).catch(() => {});

  if (currentCases.length > 0) {
    updateCoveragePanel();
    showResultWarnings();
  }
}


// ─── 補填空值案例 ────────────────────────────────────────────
async function runRefill() {
  clearError();
  const apiKey = document.getElementById('apiKeyInput').value.trim();
  if (!apiKey) {
    showError(`請先填入 ${getApiKeyLabel()}`);
    return;
  }
  if (!lastNewSpecText) {
    showError('請先執行一次完整分析，或確認已從快取載入規格書文字');
    return;
  }

  const emptyCases = currentCases.filter(c =>
    EMPTY_CHECK_FIELDS.some(f => !c[f] || c[f].trim() === '')
  );
  if (emptyCases.length === 0) return;

  const btn = document.getElementById('refillBtn');
  btn.disabled = true;
  const batches = chunkArray(emptyCases, REFILL_BATCH_SIZE);
  const totalBatches = batches.length;
  const refillMap = new Map();
  const batchFailures = [];
  let truncatedBatches = 0;

  try {
    for (let i = 0; i < totalBatches; i++) {
      if (i > 0) await llmSleep(MULTI_BATCH_THROTTLE_MS);
      btn.textContent = totalBatches > 1
        ? `⏳ 補填中 ${i + 1}/${totalBatches}…`
        : '⏳ 補填中...';

      const summary = buildRefillSummary(batches[i]);
      const prompt = PROMPT_REFILL(
        JSON.stringify(summary, null, 2),
        lastNewSpecText
      );

      try {
        const raw = await callLlm(
          getLlmProvider(), apiKey, prompt, getSelectedModelId()
        );
        const { parsed, truncated } = parseLlmJsonArray(raw);
        if (truncated) truncatedBatches++;
        parsed.forEach(r => {
          const id = r['編號'];
          if (id) refillMap.set(id, r);
        });
      } catch (err) {
        batchFailures.push({ batch: i + 1, err });
      }
    }

    if (refillMap.size > 0) {
      currentCases = mergeRefillIntoCases(currentCases, refillMap);
      refreshDisplay();
    }

    if (batchFailures.length === 0) {
      if (truncatedBatches > 0) {
        lastAiParseWarning =
          `⚠ 補填有 ${truncatedBatches} 批回傳可能已截斷，請檢查是否仍有空欄。`;
        showResultWarnings();
      }
    } else if (refillMap.size > 0) {
      const first = batchFailures[0].err;
      showError(
        `部分補填完成（${refillMap.size} 筆）；第 ${batchFailures.map(f => f.batch).join('、')} 批失敗：${
          formatApiError(first, { provider: getProviderLabel() })
        }`
      );
    } else {
      showApiError(batchFailures[0].err);
    }
  } catch (err) {
    showApiError(err);
  } finally {
    btn.disabled = false;
    updateRefillBtn();
  }
}

async function downloadXLSX(cases) {
  const wb = new ExcelJS.Workbook();
  wb.creator = 'TestCaseGenerator';
  const ws = wb.addWorksheet('測試案例', { views: [{ state: 'frozen', ySplit: 1 }] });

  const COLS = [
    { header: '狀態',   key: 'status',    width: 10 },
    { header: '取代者', key: 'replacedBy', width: 16 },
    { header: '編號',   key: 'id',         width: 20 },
    { header: '測試類型', key: 'type',     width: 10 },
    { header: '類別',   key: 'cat',        width: 10 },
    { header: '優先度', key: 'priority',   width: 10 },
    { header: '主模組', key: 'main',       width: 14 },
    { header: '層級',   key: 'tier',       width: 8 },
    { header: '功能頁面/元件', key: 'feature', width: 28 },
    { header: '前置條件', key: 'pre',      width: 30 },
    { header: '測試標題', key: 'title',    width: 45 },
    { header: '預期結果', key: 'expected', width: 35 },
    { header: '規格來源', key: 'src',      width: 16 },
    { header: '版本標籤', key: 'ver',      width: 16 },
  ];
  ws.columns = COLS;

  // 表頭樣式
  ws.getRow(1).eachCell(cell => {
    cell.fill   = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FF1E3A5F' } };
    cell.font   = { bold: true, color: { argb: 'FF74C0FC' }, size: 11 };
    cell.border = { bottom: { style: 'thin', color: { argb: 'FF74C0FC' } } };
    cell.alignment = { vertical: 'middle', wrapText: false };
  });
  ws.getRow(1).height = 22;

  const MUTED  = 'FF888888';
  const RED    = 'FFFF6B6B';
  const ORANGE = 'FFFF8C00';

  cases.forEach(c => {
    const isObsolete = !!c['_obsolete'] || c['狀態'] === '失效';
    const row = ws.addRow({
      status:    isObsolete ? '已失效（僅供參考）' : (c['狀態'] || '有效'),
      replacedBy: c['_replacedBy'] || c['取代者'] || '',
      id:        c['編號']   || '',
      type:      c['測試類型'] || '',
      cat:       c['類別']   || '',
      priority:  c['優先度'] || '',
      main:      c['主模組'] || '',
      tier:      c['層級']   || '',
      feature:   c['功能頁面/元件'] || '',
      pre:       c['前置條件'] || '',
      title:     c['測試標題'] || '',
      expected:  c['預期結果'] || '',
      src:       c['規格來源'] || '',
      ver:       c['版本標籤'] || '',
    });
    row.alignment = { wrapText: true, vertical: 'top' };

    if (isObsolete) {
      row.eachCell({ includeEmpty: true }, cell => {
        cell.font = { strike: true, color: { argb: MUTED }, size: 10 };
      });
      // 狀態欄：紅色無刪除線
      row.getCell('status').font   = { bold: true, color: { argb: RED }, size: 10 };
      // 取代者欄：藍色無刪除線
      const repVal = c['_replacedBy'];
      if (repVal) {
        row.getCell('replacedBy').font  = { color: { argb: 'FF74C0FC' }, size: 10 };
      } else {
        row.getCell('replacedBy').font  = { color: { argb: MUTED }, italic: true, size: 10 };
      }
    }

    // 空值欄位：紅色斜體
    const fieldMap = {
      '主模組': 'main', '功能頁面/元件': 'feature',
      '測試標題': 'title', '預期結果': 'expected', '規格來源': 'src'
    };
    EMPTY_CHECK_FIELDS.forEach(f => {
      if (!c[f] || c[f].trim() === '') {
        const cell = row.getCell(fieldMap[f]);
        cell.value = '—';
        cell.font  = { ...cell.font, italic: true, color: { argb: RED } };
      }
    });

    // 可疑規格來源：橙色
    if (c['_srcSuspicious']) {
      row.getCell('src').font = { ...row.getCell('src').font, color: { argb: ORANGE } };
    }
  });

  // 輸出
  const buffer = await wb.xlsx.writeBuffer();
  const blob   = new Blob([buffer], {
    type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
  });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `test_cases_${getTodayStr()}.xlsx`;
  a.click();
  URL.revokeObjectURL(a.href);
}

// ─── 主流程 ──────────────────────────────────────────────────
async function runAnalysis() {
  clearError();

  if (analysisMode === 'modularize') {
    return runModularizeAnalysis();
  }
  if (analysisMode === 'mindmap') {
    return runMindmapFromXlsx();
  }

  const apiKey  = document.getElementById('apiKeyInput').value.trim();
  const newFile = document.getElementById('newFile').files[0];
  const oldFile = document.getElementById('oldFile').files[0];
  const baselineFile = document.getElementById('baselineFile')?.files?.[0];
  const supplementFiles = getSupplementFiles();

  if (!apiKey)  { showError(`請填入 ${getApiKeyLabel()}`); return; }
  if (analysisMode === 'multi') {
    if (!supplementFiles.length) {
      showError('請至少上傳 1 份功能規格書（PRD）');
      return;
    }
    const hasIndexFile = !!(newFile && isSpecFile(newFile));
    const manualRows = collectManualIndexRowsFromUi();
    if (!hasIndexFile && !isValidManualIndexRows(manualRows)) {
      showError('請上傳模組索引檔，或於手動索引表填寫至少一列 L1 + L2');
      return;
    }
    if (newFile && !isSpecFile(newFile)) {
      showError('模組索引檔格式不支援，請使用 PDF、DOCX、XLSX 或 CSV');
      return;
    }
  } else {
    if (!newFile) { showError('請上傳新版規格書'); return; }
    if (!isSpecFile(newFile)) { showError('不支援的規格格式'); return; }
  }
  if (analysisMode === 'baseline' && !baselineFile) { showError('請上傳 Baseline TestCase（CSV/XLSX）'); return; }

  // ── 若已有結果，詢問附加或清空 ──────────────────────────────
  let appendMode = false;
  if (currentCases.length > 0) {
    const choice = await promptAppendOrReplace();
    if (choice === 'append') {
      appendMode = true;
    } else {
      currentCases = [];
    }
  }

  document.getElementById('statusPanel').classList.add('visible');
  if (!appendMode) {
    document.getElementById('resultSection').classList.remove('visible');
    clearResultFilters();
  }
  document.getElementById('analyzeBtn').disabled = true;
  analysisInProgress = true;
  setExportEnabled(false);
  if (!appendMode) {
    lastXlsxSheetBatchState = null;
    lastXlsxSheetCoverageWarning = null;
    hideBatchRetryBar();
  }

  try {
    // ── 多規格生成 ────────────────────────────────────────────
    if (analysisMode === 'multi') {
      setStep(1, 'running');
      document.getElementById('step1Text').textContent = '解析模組索引與功能規格書...';

      let indexSource;
      if (newFile && isSpecFile(newFile)) {
        const newResult = await extractSpecFile(newFile, 'newFile');
        lastSpecExtractSummary = formatExtractSummary(newResult.meta);
        showSpecExtractNote(lastSpecExtractSummary);
        indexSource = { name: newFile.name, text: newResult.text };
      } else {
        lastSpecExtractSummary = '';
        showSpecExtractNote('');
        const manualRows = collectManualIndexRowsFromUi();
        indexSource = {
          name: '模組索引（手動輸入）',
          text: formatManualIndexForPrompt(manualRows),
          manualOutline: buildOutlineFromManualRows(manualRows),
        };
      }

      const supplementDocs = [];
      const sortedSupplementFiles = [...supplementFiles].sort((a, b) => a.name.localeCompare(b.name, 'zh-Hant'));
      for (const file of sortedSupplementFiles) {
        const { text } = (await extractSpecFile(file, 'supplementFiles'));
        supplementDocs.push({ name: file.name, text });
      }

      const promptLabel = indexSource.name.includes('手動')
        ? `手動索引 + 功能規格書 ${supplementDocs.length} 份`
        : `模組索引 ${indexSource.name} + 功能規格書 ${supplementDocs.length} 份`;
      lastNewSpecText = buildMultiSpecBundle(indexSource.name, indexSource.text, supplementDocs);
      lastSpecSourceFilename = '';

      setStep(1, 'done');
      document.getElementById('step1Text').textContent = `規格解析完成（${promptLabel}）`;

      await finishMultiSpecAnalysis({
        apiKey, indexSource, supplementDocs, appendMode
      });
      return;
    }

    // Step 1：解析規格
    setStep(1, 'running');
    document.getElementById('step1Text').textContent = `解析規格文字...`;

    const newResult = await extractSpecFile(newFile, 'newFile');
    const newText = newResult.text;
    lastSpecExtractSummary = formatExtractSummary(newResult.meta);
    showSpecExtractNote(lastSpecExtractSummary);
    let specTextForPrompt = newText;
    if (analysisMode === 'spec' || analysisMode === 'baseline') {
      lastSpecSourceFilename = newFile.name;
      specTextForPrompt = wrapSpecDocument(newFile.name, newText);
    } else {
      lastSpecSourceFilename = '';
    }
    lastNewSpecText = specTextForPrompt;
    lastSpecOutline = buildSpecOutline(newText);
    lastIndexOutline = { mainOrder: [], items: [] };
    lastContentOutline = { mainOrder: [], items: [] };

    // 決定舊版文字來源：上傳的檔案 > 快取 > 無
    let oldText     = null;
    let oldLabel    = '';
    let oldFilename = '';
    if (analysisMode === 'spec' && oldFile) {
      const oldResult = await extractSpecFile(oldFile, 'oldFile');
      oldText = oldResult.text;
      oldLabel = oldFile.name;
      oldFilename = oldFile.name;
    } else if (analysisMode === 'spec' && useCache && cachedSpec) {
      oldText  = cachedSpec.text;
      oldLabel = `${cachedSpec.filename}（快取）`;
      oldFilename = cachedSpec.filename || '';
    }

    setStep(1, 'done');
    const specModeSuffix = analysisMode === 'spec'
      ? (oldText ? `，舊版 ${oldLabel}，差異比對` : '，全量產出（單檔）')
      : '';
    document.getElementById('step1Text').textContent =
      analysisMode === 'baseline'
        ? `規格解析完成（新版 ${newFile.name}）`
        : `規格解析完成（新版 ${newFile.name}${specModeSuffix}）`;

    const selectedSheets = newResult.meta?.selected || [];
    const useXlsxSheetBatch =
      analysisMode === 'spec' &&
      !oldText &&
      getSpecFormat(newFile) === 'xlsx' &&
      selectedSheets.length >= 2;

    if (useXlsxSheetBatch) {
      await finishXlsxSheetAnalysis({
        apiKey,
        newFile,
        newText,
        selectedSheets,
        appendMode,
        specTextForPrompt,
      });
      return;
    }

    // Step 2：呼叫 Gemini AI（含進度條）
    setStep(2, 'running');
    const mode = analysisMode === 'baseline'
      ? '匯入Case比對模式'
      : (oldText ? '差異比對模式' : '全量產出（單檔）');
    document.getElementById('step2Text').textContent = `呼叫 ${getProviderLabel()} AI（${mode}）...`;

    // 啟動假進度條
    const progressWrap = document.getElementById('aiProgressWrap');
    const progressFill = document.getElementById('aiProgressFill');
    const progressPct  = document.getElementById('aiProgressPct');
    const progressSec  = document.getElementById('aiProgressSec');
    progressWrap.style.display = 'flex';
    let fakeProgress = 0;
    let elapsedSec   = 0;
    const progressTimer = setInterval(() => {
      elapsedSec++;
      // 速度逐漸變慢：前 30 秒較快，之後緩行，最多到 92%
      const speed = fakeProgress < 50 ? 2.5 : fakeProgress < 75 ? 1.2 : 0.4;
      fakeProgress = Math.min(fakeProgress + speed * (Math.random() * 0.8 + 0.6), 92);
      progressFill.style.width = fakeProgress + '%';
      progressPct.textContent  = Math.floor(fakeProgress) + '%';
      progressSec.textContent  = `已等待 ${elapsedSec} 秒`;
    }, 1000);

    let rawText;
    try {
      let prompt;
      if (analysisMode === 'baseline') {
        const baselineCases = await loadBaselineCasesFromFile(baselineFile);
        const baselineSummary = baselineCases.map(c => ({
          編號: c['編號'],
          測試類型: c['測試類型'],
          類別: c['類別'],
          優先度: c['優先度'],
          主模組: c['主模組'],
          層級: c['層級'],
          '功能頁面/元件': c['功能頁面/元件'],
          前置條件: c['前置條件'],
          測試標題: c['測試標題'],
          預期結果: c['預期結果'],
          規格來源: c['規格來源'],
          版本標籤: c['版本標籤']
        }));
        prompt = buildBaselinePrompt(specTextForPrompt, JSON.stringify(baselineSummary, null, 2));
      } else {
        prompt = oldText
          ? buildDiffPrompt(
            wrapSpecDocument(newFile.name, newText),
            wrapSpecDocument(oldFilename, oldText)
          )
          : buildFullPrompt(specTextForPrompt);
      }
      rawText = await callLlm(getLlmProvider(), apiKey, prompt, getSelectedModelId());
    } finally {
      clearInterval(progressTimer);
      progressFill.style.width = '100%';
      progressPct.textContent  = '100%';
      await new Promise(r => setTimeout(r, 300));
      progressWrap.style.display = 'none';
    }

    setStep(2, 'done');
    document.getElementById('step2Text').textContent = `AI 分析完成（共耗時 ${elapsedSec} 秒）`;

    // Step 3：解析與格式化
    setStep(3, 'running');
    document.getElementById('step3Text').textContent = `處理並格式化結果...`;

    lastMultiPrdCoverageWarning = null;
    const truncateContext = (
      analysisMode === 'spec' &&
      !oldText &&
      getSpecFormat(newFile) === 'xlsx' &&
      (newResult.meta?.sheets?.length || 0) >= 2
    ) ? { type: 'full-xlsx' } : null;
    const rawCases = parseAiJson(rawText, truncateContext).map(c => ({
      ...c,
      '狀態': c['狀態'] || '有效',
      '取代者': c['取代者'] || ''
    }));
    if (analysisMode === 'multi' && supplementDocs.length) {
      lastMultiPrdCoverageWarning = checkMultiPrdCoverage(supplementDocs, rawCases);
    }
    const versionPrefix = document.getElementById('verPrefixInput').value.trim();

    // 差異比對 + 附加模式 + 有前綴 → 新案例編號加前綴
    const newCases = (versionPrefix && oldText && appendMode && analysisMode === 'spec')
      ? rawCases.map(c => ({ ...c, '編號': c['編號'] ? `${versionPrefix}_${c['編號']}` : c['編號'] }))
      : rawCases;

    if (appendMode) {
      currentCases = [...currentCases, ...newCases];
    } else {
      currentCases = newCases;
    }
    if (analysisMode === 'baseline') {
      currentCases = dedupeCasesWithObsoleteMark(currentCases);
    }
    currentCases = currentCases.map(c => normalizeCaseEntry(c, lastSpecOutline));
    currentCases = sortCasesByOutline(currentCases, lastSpecOutline);

    setStep(3, 'done');
    document.getElementById('step3Text').textContent =
      appendMode
        ? `附加完成！目前共 ${currentCases.length} 個測試案例（本次新增 ${newCases.length} 個）`
        : `完成！共產出 ${currentCases.length} 個測試案例`;

    if (analysisMode === 'spec' && !oldText) {
      applySpecFullCoverage(
        newFile,
        currentCases,
        getSpecFormat(newFile) === 'xlsx' ? (newResult.meta?.selected || []) : []
      );
    }

    refreshDisplay();
    showResultWarnings();
    document.getElementById('resultSection').classList.add('visible');

    // ── Step V：附加模式 + 有舊版規格 → 驗證既有案例有效性 ──────
    if (analysisMode === 'spec' && appendMode && oldText) {
      const casesBeforeAppend = currentCases.slice(0, currentCases.length - newCases.length);
      if (casesBeforeAppend.length > 0) {
        const obsoleteList = await runObsoleteCheck(apiKey, newText, casesBeforeAppend, newCases);
        if (obsoleteList.length > 0) {
          const obsoleteMap = new Map(obsoleteList.map(o => [o.id, o.replacedBy]));
          currentCases = currentCases.map(c => {
            if (obsoleteMap.has(c['編號'])) {
              return { ...c, _obsolete: true, _replacedBy: obsoleteMap.get(c['編號']) };
            }
            return c;
          });
          refreshDisplay();
        }
      }
    }

    // ── 分析成功後，將新版規格書文字存入 IndexedDB ──────────────
    try {
      const cacheFilename = analysisMode === 'multi'
        ? `${newFile.name}${supplementDocs.length ? ` +${supplementDocs.length}份PRD` : ''}`
        : newFile.name;
      await dbSaveSpec(cacheFilename, specTextForPrompt);
      const spec = { filename: cacheFilename, text: specTextForPrompt, savedAt: new Date().toLocaleString('zh-TW') };
      showCacheNotice(spec);
      // 若剛才是以舊快取做比對，清除 useCache 狀態（已完成本次比對）
      if (useCache) deactivateCache();
    } catch (_) {}

  } catch (err) {
    const step = [1, 2, 3].find(n =>
      document.getElementById(`step${n}Icon`).classList.contains('running')
    ) || 1;
    setStep(step, 'error');
    showApiError(err);
  } finally {
    analysisInProgress = false;
    setExportEnabled(true);
    document.getElementById('analyzeBtn').disabled = false;
    checkReady();
  }
}

// ─── API Key 管理 ────────────────────────────────────────────
document.getElementById('saveKeyBtn').addEventListener('click', () => {
  const key = document.getElementById('apiKeyInput').value.trim();
  if (!key) { alert('請先輸入 API Key'); return; }
  persistApiKeyForProvider(getLlmProvider(), key);
  activeLlmProvider = getLlmProvider();
  const btn = document.getElementById('saveKeyBtn');
  btn.textContent = '✅ 已儲存';
  setTimeout(() => { btn.textContent = '💾 儲存'; }, 1500);
});

let keyVisible = false;
document.getElementById('toggleKeyBtn').addEventListener('click', () => {
  keyVisible = !keyVisible;
  document.getElementById('apiKeyInput').type = keyVisible ? 'text' : 'password';
  document.getElementById('toggleKeyBtn').textContent = keyVisible ? '🙈 隱藏' : '👁 顯示';
});

function isNewFileXlsxReady() {
  const file = document.getElementById('newFile')?.files?.[0];
  return isFileXlsxSheetReady(file);
}

function onSpecFilePicked(fileInputId, file) {
  if (!file) return;
  if (!isSpecFile(file)) {
    showError('不支援的規格格式，請使用 PDF、DOCX、XLSX 或 CSV');
    return;
  }
  handleSpecFileChange(fileInputId, file).catch(err => showError(err.message));
}

// ─── 檔案上傳 UI ─────────────────────────────────────────────
function setupFileZone(fileInputId, zoneId, fileNameId, validator) {
  const input = document.getElementById(fileInputId);
  const zone  = document.getElementById(zoneId);
  const label = document.getElementById(fileNameId);

  input.addEventListener('change', () => {
    const file = input.files[0];
    if (file && (!validator || validator(file))) {
      label.textContent = `📎 ${file.name}`;
      zone.classList.add('has-file');
      // 上傳檔案到舊版區時，取消快取模式
      if (fileInputId === 'oldFile' && useCache) deactivateCache();
      if (fileInputId === 'newFile' || fileInputId === 'oldFile') {
        onSpecFilePicked(fileInputId, file);
      }
      if (fileInputId === 'newFile') syncManualIndexDisabled();
      checkReady();
    }
  });

  zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('drag-over'); });
  zone.addEventListener('dragleave', () => zone.classList.remove('drag-over'));
  zone.addEventListener('drop', e => {
    e.preventDefault();
    zone.classList.remove('drag-over');
    const file = e.dataTransfer.files[0];
    if (file && (!validator || validator(file))) {
      const dt = new DataTransfer();
      dt.items.add(file);
      input.files = dt.files;
      label.textContent = `📎 ${file.name}`;
      zone.classList.add('has-file');
      if (fileInputId === 'oldFile' && useCache) deactivateCache();
      if (fileInputId === 'newFile' || fileInputId === 'oldFile') {
        onSpecFilePicked(fileInputId, file);
      }
      if (fileInputId === 'newFile') syncManualIndexDisabled();
      checkReady();
    }
  });
}

function setupMultiFileZone(fileInputId, zoneId, fileNameId, validator) {
  const input = document.getElementById(fileInputId);
  const zone  = document.getElementById(zoneId);
  const label = document.getElementById(fileNameId);

  const render = () => {
    const files = Array.from(input.files || []).filter(f => !validator || validator(f));
    label.textContent = formatSupplementLabel(files);
    zone.classList.toggle('has-file', files.length > 0);
    handleSupplementFilesChange().catch(err => showError(err.message));
    checkReady();
  };

  input.addEventListener('change', render);

  zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('drag-over'); });
  zone.addEventListener('dragleave', () => zone.classList.remove('drag-over'));
  zone.addEventListener('drop', e => {
    e.preventDefault();
    zone.classList.remove('drag-over');
    const files = Array.from(e.dataTransfer.files || []).filter(f => !validator || validator(f));
    if (!files.length) return;
    const dt = new DataTransfer();
    files.forEach(f => dt.items.add(f));
    input.files = dt.files;
    render();
  });
}

// ─── 版本前綴輔助 ────────────────────────────────────────────
function hasOldSpec() {
  if (analysisMode !== 'spec') return false;
  return document.getElementById('oldFile').files.length > 0 || (useCache && !!cachedSpec);
}

function isPrefixRequired() {
  return currentCases.length > 0 && hasOldSpec();
}

function updatePrefixUI() {
  const row    = document.getElementById('verPrefixRow');
  const badge  = document.getElementById('verPrefixBadge');
  const input  = document.getElementById('verPrefixInput');
  const hint   = document.getElementById('verPrefixHint');
  const exEl   = document.getElementById('verPrefixExample');
  const hasOld = hasOldSpec();

  // 只有舊版規格存在才顯示此欄位
  if (!hasOld) { row.style.display = 'none'; return; }
  row.style.display = '';

  const required = isPrefixRequired();
  const val      = input.value.trim();

  badge.textContent = required ? '差異比對必填' : '差異比對選填';
  badge.style.background = required ? 'rgba(255,107,107,.15)' : 'rgba(255,212,59,.15)';
  badge.style.color      = required ? 'var(--red)'            : 'var(--yellow)';
  badge.style.borderColor= required ? 'rgba(255,107,107,.3)'  : 'rgba(255,212,59,.3)';

  const prefix   = val || 'V2';
  if (exEl) exEl.textContent = `${prefix}_POS_LOB_001`;

  // 必填且空白 → 標紅
  if (required && !val) {
    input.classList.add('required-empty');
    hint.innerHTML = `<span style="color:var(--red);font-weight:600;">⚠️ 請填入版本前綴，避免與既有 ${currentCases.length} 個案例的編號重複</span>`;
  } else {
    input.classList.remove('required-empty');
    hint.innerHTML = `新增案例的編號將加上此前綴（如 <strong id="verPrefixExample">${prefix}_POS_LOB_001</strong>），避免與既有案例編號重複`;
  }
}

function checkReady() {
  const hasApiKey  = document.getElementById('apiKeyInput').value.trim().length > 0;
  const hasNewFile = document.getElementById('newFile').files.length > 0;
  const hasBaseline = document.getElementById('baselineFile')?.files.length > 0;
  const hasBatchA = document.getElementById('batchFileA')?.files?.length > 0;
  const hasBatchB = document.getElementById('batchFileB')?.files?.length > 0;
  const useAiMod = document.getElementById('modUseAiConfirm')?.checked;
  const required   = isPrefixRequired();
  const hasPrefix  = document.getElementById('verPrefixInput').value.trim().length > 0;
  let modeReady = false;
  const hasMindmapFile = document.getElementById('mindmapFile')?.files?.length > 0;
  if (analysisMode === 'modularize') {
    modeReady = hasBatchA && hasBatchB && (!useAiMod || hasApiKey);
  } else if (analysisMode === 'mindmap') {
    modeReady = hasMindmapFile;
  } else if (analysisMode === 'multi') {
    const hasPrd = getSupplementFiles().length > 0;
    const newFile = document.getElementById('newFile')?.files?.[0];
    const hasIndexFile = !!(newFile && isSpecFile(newFile) && isFileXlsxSheetReady(newFile));
    const hasManualIndex = isValidManualIndexRows(collectManualIndexRowsFromUi());
    modeReady = hasApiKey && hasPrd && areSupplementXlsxFilesReady() && (hasIndexFile || hasManualIndex);
  } else if (analysisMode === 'baseline') {
    modeReady = hasApiKey && hasNewFile && hasBaseline && isNewFileXlsxReady();
  } else {
    modeReady = hasApiKey && hasNewFile && isNewFileXlsxReady() && (!required || hasPrefix);
  }
  document.getElementById('analyzeBtn').disabled = !modeReady;
  updatePrefixUI();
}

document.getElementById('apiKeyInput').addEventListener('input', checkReady);
document.getElementById('verPrefixInput').addEventListener('input', checkReady);
document.getElementById('baselineFile')?.addEventListener('change', checkReady);
document.getElementById('batchFileA')?.addEventListener('change', checkReady);
document.getElementById('batchFileB')?.addEventListener('change', checkReady);
document.getElementById('batchFileC')?.addEventListener('change', checkReady);
document.getElementById('modUseAiConfirm')?.addEventListener('change', checkReady);
document.getElementById('mindmapFile')?.addEventListener('change', checkReady);

// ─── API Key 說明展開/收合 ────────────────────────────────────
document.getElementById('helpKeyBtn').addEventListener('click', () => {
  const provider = getLlmProvider();
  const geminiBox = document.getElementById('apiHelpBox');
  const sirayaBox = document.getElementById('sirayaHelpBox');
  const activeBox = provider === PROVIDER_SIRAYA ? sirayaBox : geminiBox;
  const inactiveBox = provider === PROVIDER_SIRAYA ? geminiBox : sirayaBox;
  inactiveBox?.classList.remove('visible');
  const btn = document.getElementById('helpKeyBtn');
  const open = activeBox.classList.toggle('visible');
  btn.textContent = open ? '❓ 如何取得 Key ▴' : '❓ 如何取得 Key ▾';
});

setupFileZone('newFile', 'newZone', 'newFileName', isSpecFile);
setupFileZone('oldFile', 'oldZone', 'oldFileName', isSpecFile);
setupMultiFileZone('supplementFiles', 'supplementZone', 'supplementFileName', isSpecFile);
setupFileZone(
  'baselineFile',
  'baselineZone',
  'baselineFileName',
  f => /\.csv$/i.test(f.name) || /\.xlsx$/i.test(f.name)
);
setupFileZone('batchFileA', 'batchAZone', 'batchFileAName', f => /\.csv$/i.test(f.name) || /\.xlsx$/i.test(f.name));
setupFileZone('batchFileB', 'batchBZone', 'batchFileBName', f => /\.csv$/i.test(f.name) || /\.xlsx$/i.test(f.name));
setupFileZone('batchFileC', 'batchCZone', 'batchFileCName', f => /\.csv$/i.test(f.name) || /\.xlsx$/i.test(f.name));
setupFileZone(
  'mindmapFile',
  'mindmapFileZone',
  'mindmapFileName',
  f => /\.csv$/i.test(f.name) || /\.xlsx$/i.test(f.name)
);

function setAnalysisMode(mode) {
  const prevMode = analysisMode;
  analysisMode = mode;
  const specBtn = document.getElementById('modeSpecBtn');
  const multiBtn = document.getElementById('modeMultiBtn');
  const modBtn = document.getElementById('modeModularBtn');
  const mindBtn = document.getElementById('modeMindmapBtn');
  const baseBtn = document.getElementById('modeBaselineBtn');
  const baselineWrap = document.getElementById('baselineWrap');
  const supplementWrap = document.getElementById('supplementWrap');
  const modularizeWrap = document.getElementById('modularizeWrap');
  const mindmapUploadWrap = document.getElementById('mindmapUploadWrap');
  const newFileCol = document.getElementById('newFileCol');
  const oldFileCol = document.getElementById('oldFileCol');
  const cacheNotice = document.getElementById('cacheNotice');
  const newFileTitle = document.getElementById('newFileTitle');
  const newFileSub = document.getElementById('newFileSub');
  const manualIndexWrap = document.getElementById('manualIndexWrap');
  const promptCard = document.querySelector('.right-col');
  const analyzeBtn = document.getElementById('analyzeBtn');

  [specBtn, multiBtn, modBtn, mindBtn, baseBtn].forEach(b => b?.classList.remove('active'));
  if (prevMode === 'mindmap' && mode !== 'mindmap') {
    leaveMindmapMode();
  }

  if (mode === 'baseline') {
    baseBtn.classList.add('active');
    baselineWrap.style.display = '';
    if (supplementWrap) supplementWrap.style.display = 'none';
    if (modularizeWrap) modularizeWrap.style.display = 'none';
    if (mindmapUploadWrap) mindmapUploadWrap.style.display = 'none';
    if (newFileCol) newFileCol.style.display = '';
    if (oldFileCol) oldFileCol.style.display = 'none';
    if (cacheNotice) cacheNotice.style.display = 'none';
    if (manualIndexWrap) manualIndexWrap.style.display = 'none';
    if (newFileTitle) newFileTitle.textContent = '新版規格書（必填）';
    if (newFileSub) newFileSub.textContent = 'PDF / DOCX / XLSX / CSV';
    if (promptCard) promptCard.style.opacity = '';
    if (analyzeBtn) analyzeBtn.textContent = '🚀 開始分析';
    document.getElementById('verPrefixRow').style.display = 'none';
    document.getElementById('exportCsvBtn').textContent = '📊 匯出 XLSX';
    toggleModularizeTableColumns(false);
    activatePromptTab('baseline');
  } else if (mode === 'multi') {
    multiBtn.classList.add('active');
    baselineWrap.style.display = 'none';
    if (supplementWrap) supplementWrap.style.display = '';
    if (modularizeWrap) modularizeWrap.style.display = 'none';
    if (mindmapUploadWrap) mindmapUploadWrap.style.display = 'none';
    if (newFileCol) newFileCol.style.display = '';
    if (oldFileCol) oldFileCol.style.display = 'none';
    if (cacheNotice) cacheNotice.style.display = 'none';
    if (manualIndexWrap) manualIndexWrap.style.display = '';
    if (newFileTitle) newFileTitle.textContent = '模組索引檔（選填）';
    if (newFileSub) newFileSub.textContent = '上傳大平台模組表，或改用下方手動索引（二選一）';
    syncManualIndexDisabled();
    if (promptCard) promptCard.style.opacity = '';
    if (analyzeBtn) analyzeBtn.textContent = '🚀 開始分析';
    document.getElementById('verPrefixRow').style.display = 'none';
    document.getElementById('exportCsvBtn').textContent = '📊 匯出 XLSX';
    toggleModularizeTableColumns(false);
    activatePromptTab('multi');
  } else if (mode === 'modularize') {
    modBtn.classList.add('active');
    baselineWrap.style.display = 'none';
    if (supplementWrap) supplementWrap.style.display = 'none';
    if (modularizeWrap) modularizeWrap.style.display = '';
    if (mindmapUploadWrap) mindmapUploadWrap.style.display = 'none';
    if (manualIndexWrap) manualIndexWrap.style.display = 'none';
    if (newFileCol) newFileCol.style.display = 'none';
    if (oldFileCol) oldFileCol.style.display = 'none';
    if (cacheNotice) cacheNotice.style.display = 'none';
    if (promptCard) promptCard.style.opacity = '0.45';
    if (analyzeBtn) analyzeBtn.textContent = '🔗 開始模組化';
    document.getElementById('verPrefixRow').style.display = 'none';
    document.getElementById('exportCsvBtn').textContent = '📊 匯出模組化報表';
    activatePromptTab('full');
  } else if (mode === 'mindmap') {
    mindBtn.classList.add('active');
    baselineWrap.style.display = 'none';
    if (supplementWrap) supplementWrap.style.display = 'none';
    if (modularizeWrap) modularizeWrap.style.display = 'none';
    if (mindmapUploadWrap) mindmapUploadWrap.style.display = '';
    if (manualIndexWrap) manualIndexWrap.style.display = 'none';
    if (newFileCol) newFileCol.style.display = 'none';
    if (oldFileCol) oldFileCol.style.display = 'none';
    if (cacheNotice) cacheNotice.style.display = 'none';
    if (promptCard) promptCard.style.opacity = '0.35';
    if (analyzeBtn) analyzeBtn.textContent = '🧠 產生心智圖';
    document.getElementById('verPrefixRow').style.display = 'none';
    document.getElementById('exportCsvBtn').textContent = '📊 匯出 XLSX';
    toggleModularizeTableColumns(false);
    document.getElementById('step2Text').textContent = '合併平台案例與目錄樹...';
    document.getElementById('step3Text').textContent = '渲染目錄瀏覽與樹狀總覽...';
    enterMindmapMode();
  } else {
    specBtn.classList.add('active');
    baselineWrap.style.display = 'none';
    if (supplementWrap) supplementWrap.style.display = 'none';
    if (modularizeWrap) modularizeWrap.style.display = 'none';
    if (mindmapUploadWrap) mindmapUploadWrap.style.display = 'none';
    if (newFileCol) newFileCol.style.display = '';
    if (oldFileCol) oldFileCol.style.display = '';
    if (cacheNotice && cachedSpec) cacheNotice.style.display = '';
    if (manualIndexWrap) manualIndexWrap.style.display = 'none';
    if (newFileTitle) newFileTitle.textContent = '新版規格書（必填）';
    if (newFileSub) newFileSub.textContent = 'PDF / DOCX / XLSX / CSV';
    if (promptCard) promptCard.style.opacity = '';
    if (analyzeBtn) analyzeBtn.textContent = '🚀 開始分析';
    document.getElementById('exportCsvBtn').textContent = '📊 匯出 XLSX';
    toggleModularizeTableColumns(false);
    activatePromptTab('diff');
  }

  if (prevMode === 'mindmap' && mode !== 'mindmap') {
    const resultVisible = document.getElementById('resultSection')?.classList.contains('visible');
    if (resultVisible && currentCases.length) refreshDisplay();
  }

  syncXlsxSheetPanel().catch(() => {});
  checkReady();
}

document.getElementById('modeSpecBtn').addEventListener('click', () => setAnalysisMode('spec'));
document.getElementById('modeMultiBtn').addEventListener('click', () => setAnalysisMode('multi'));
document.getElementById('modeModularBtn').addEventListener('click', () => setAnalysisMode('modularize'));
document.getElementById('modeBaselineBtn').addEventListener('click', () => setAnalysisMode('baseline'));
document.getElementById('modeMindmapBtn').addEventListener('click', () => setAnalysisMode('mindmap'));

document.getElementById('analyzeBtn').addEventListener('click', runAnalysis);

document.getElementById('viewTabTable')?.addEventListener('click', () => setResultView('table'));
document.getElementById('viewTabDuplicate')?.addEventListener('click', () => setResultView('duplicate'));
document.getElementById('viewTabMindmap')?.addEventListener('click', () => setResultView('mindmap'));

document.getElementById('mindmapTabBrowse')?.addEventListener('click', () => setMindmapSubView('browse'));
document.getElementById('mindmapTabTree')?.addEventListener('click', () => setMindmapSubView('tree'));
document.getElementById('mindmapNavSearch')?.addEventListener('input', (e) => {
  if (lastMindmapExport?.tree) renderMindmapNav(lastMindmapExport.tree.roots, e.target.value);
});
function mindmapSetAllCardsCollapsed(collapsed) {
  const container = getActiveMindmapCardsContainer();
  if (!container) return;
  setAllMindmapCardsCollapsed(container, collapsed);
  refreshMindmapCardsCollapseUi(container);
}
document.getElementById('mindmapCollapseAllBtn')?.addEventListener('click', () => mindmapSetAllCardsCollapsed(true));
document.getElementById('mindmapExpandAllBtn')?.addEventListener('click', () => mindmapSetAllCardsCollapsed(false));
document.getElementById('mindmapTreeCollapseAllBtn')?.addEventListener('click', () => mindmapSetAllCardsCollapsed(true));
document.getElementById('mindmapTreeExpandAllBtn')?.addEventListener('click', () => mindmapSetAllCardsCollapsed(false));

document.getElementById('selectAllDup')?.addEventListener('change', (e) => {
  const ids = getDuplicateCases(currentCases).map(c => c['編號']).filter(Boolean);
  if (e.target.checked) ids.forEach(id => selectedCaseIds.add(id));
  else ids.forEach(id => selectedCaseIds.delete(id));
  refreshDisplay();
});

document.getElementById('exportMindmapBtn')?.addEventListener('click', () => {
  if (!lastMindmapExport) return;
  const btn = document.getElementById('exportMindmapBtn');
  btn.disabled = true;
  const stamp = getTodayStr();
  try {
    downloadTextFile(`mindmap_${stamp}.mmd`, lastMindmapExport.mermaid, 'text/plain;charset=utf-8');
    downloadTextFile(`mindmap_${stamp}.md`, lastMindmapExport.markdown, 'text/markdown;charset=utf-8');
  } finally {
    btn.disabled = false;
  }
});

document.getElementById('deleteSelectedBtn')?.addEventListener('click', deleteSelectedCases);

document.getElementById('selectAllCases')?.addEventListener('change', (e) => {
  const filtered = filterCases(currentCases);
  const ids = filtered.map(c => c['編號']).filter(Boolean);
  if (e.target.checked) ids.forEach(id => selectedCaseIds.add(id));
  else ids.forEach(id => selectedCaseIds.delete(id));
  refreshDisplay();
});

document.getElementById('batchRetryBtn')?.addEventListener('click', () => {
  if (lastXlsxSheetBatchState?.failedIndices?.length) {
    retryFailedXlsxSheetBatches();
  } else {
    retryFailedMultiBatches();
  }
});

document.getElementById('exportCsvBtn').addEventListener('click', async () => {
  if (analysisInProgress) {
    showError('分析進行中，請待全部 PRD 批次完成後再匯出。');
    return;
  }
  if (typeof ExcelJS === 'undefined') {
    showError('ExcelJS 尚未載入。請確認網路可連線 CDN，並以 http://localhost 開啟工具（勿用 file:// 直接開檔）。');
    return;
  }

  if (lastModularizeResult && lastAnalysisWasModularize) {
    const btn = document.getElementById('exportCsvBtn');
    btn.disabled = true;
    btn.textContent = '⏳ 產生中...';
    try {
      await downloadModularizeXLSX(lastModularizeResult);
    } catch (err) {
      showError('匯出失敗：' + (err.message || String(err)));
    } finally {
      btn.disabled = false;
      btn.textContent = '📊 匯出模組化報表';
    }
    return;
  }

  if (currentCases.length === 0) {
    showError('沒有可匯出的案例，請先完成分析。');
    return;
  }

  const btn = document.getElementById('exportCsvBtn');
  btn.disabled = true;
  btn.textContent = '⏳ 產生中...';
  try {
    const toExport = sortState.col
      ? sortCases(currentCases)
      : sortCasesByOutline(currentCases, lastSpecOutline);
    if (!toExport.length) {
      showError('沒有可匯出的案例，請先完成分析。');
      return;
    }
    await downloadXLSX(toExport);
  } catch (err) {
    showError('匯出失敗：' + (err.message || String(err)));
  } finally {
    btn.disabled = false;
    btn.textContent = '📊 匯出 XLSX';
  }
});

document.getElementById('reAnalyzeBtn').addEventListener('click', () => {
  document.getElementById('resultSection').classList.remove('visible');
  document.getElementById('statusPanel').classList.remove('visible');
  document.getElementById('stepV').style.display = 'none';
  document.getElementById('removeObsoleteBtn').style.display = 'none';
  document.getElementById('refillBtn').style.display = 'none';
  clearError();
  clearResultFilters();
  currentCases = [];
  selectedCaseIds = new Set();
  lastNewSpecText = null;
  lastModularizeResult = null;
  lastAnalysisWasModularize = false;
  lastMultiBatchState = null;
  lastXlsxSheetBatchState = null;
  hideBatchRetryBar();
  lastCoverageDocNames = [];
  lastXlsxSheetNames = [];
  lastXlsxSheetCoverageWarning = null;
  coverageInspectCases = null;
  coverageBaselineCases = null;
  const coverageTa = document.getElementById('coveragePrdList');
  if (coverageTa) coverageTa.value = '';
  document.getElementById('coveragePanel')?.classList.remove('visible');
  document.getElementById('coverageReport').innerHTML = '';
  resetMindmapResultUi();
  toggleModularizeTableColumns(false);
  const titleEl = document.querySelector('.result-header .card-title');
  if (titleEl) titleEl.textContent = '✅ 產出完成';
  document.getElementById('caseBreakdown').innerHTML = '';
  dbClearCases().catch(() => {});
});

document.getElementById('removeObsoleteBtn').addEventListener('click', () => {
  const before = currentCases.length;
  currentCases = currentCases.filter(c => !c['_obsolete']);
  refreshDisplay();
  const removed = before - currentCases.length;
  const btn = document.getElementById('removeObsoleteBtn');
  btn.textContent = `✅ 已移除 ${removed} 筆`;
  setTimeout(() => { btn.style.display = 'none'; }, 2000);
});

// ─── 快取提示欄按鈕 ──────────────────────────────────────────
document.getElementById('useAsOldBtn').addEventListener('click', () => {
  if (!cachedSpec) return;
  if (useCache) {
    deactivateCache();
    return;
  }

  // 若舊版區已有上傳檔案，先確認是否改用快取
  if (document.getElementById('oldFile').files.length > 0) {
    if (!confirm(`目前舊版區已上傳檔案，確定改用快取版本「${cachedSpec.filename}」嗎？`)) return;
    document.getElementById('oldFile').value = '';
    document.getElementById('oldFileName').textContent = '';
    document.getElementById('oldZone').classList.remove('has-file');
  }

  // 若新版區已有上傳檔案，提示使用者需重新上傳新版
  const hasNewFile = document.getElementById('newFile').files.length > 0;
  const newFileName = hasNewFile ? document.getElementById('newFile').files[0].name : '';
  if (hasNewFile) {
    if (!confirm(`啟用快取「${cachedSpec.filename}」作為舊版比對後，\n新版規格書「${newFileName}」將被清空，請重新上傳新版規格書。\n\n確定繼續嗎？`)) return;
    // 清空新版區
    document.getElementById('newFile').value = '';
    document.getElementById('newFileName').textContent = '';
    document.getElementById('newZone').classList.remove('has-file');
  }

  activateCache();
});

document.getElementById('clearCacheBtn').addEventListener('click', async () => {
  if (!confirm('確定清除快取版本嗎？')) return;
  await dbClearSpec();
  hideCacheNotice();
});

// ─── 提示詞編輯器 ────────────────────────────────────────────
function getDefaultFullTemplate() {
  return PROMPT_FULL('{{SPEC}}');
}
function getDefaultDiffTemplate() {
  return PROMPT_DIFF('{{NEW_SPEC}}', '{{OLD_SPEC}}');
}
function getDefaultBaselineTemplate() {
  return PROMPT_BASELINE_DIFF('{{NEW_SPEC}}', '{{BASELINE_CASES}}');
}

function buildFullPrompt(newText) {
  const tpl = document.getElementById('promptFullTA').value;
  return tpl.replace('{{SPEC}}', newText);
}

function getDefaultMultiTemplate() {
  return PROMPT_MULTI;
}
function buildDiffPrompt(newText, oldText) {
  return document.getElementById('promptDiffTA').value
    .replace('{{NEW_SPEC}}', newText)
    .replace('{{OLD_SPEC}}', oldText);
}
function buildBaselinePrompt(newText, baselineCasesJson) {
  return document.getElementById('promptBaselineTA').value
    .replace('{{NEW_SPEC}}', newText)
    .replace('{{BASELINE_CASES}}', baselineCasesJson);
}

function initPromptTextareas() {
  document.getElementById('promptFullTA').value = getDefaultFullTemplate();
  document.getElementById('promptDiffTA').value = getDefaultDiffTemplate();
  document.getElementById('promptBaselineTA').value = getDefaultBaselineTemplate();
  const multiTa = document.getElementById('promptMultiTA');
  if (multiTa) multiTa.value = getDefaultMultiTemplate();
}

// ─── 已儲存提示詞（多筆命名，localStorage）────────────────────
const PROMPT_SAVED_STORAGE_KEY = 'prompt_saved_library';
const PROMPT_MODE_TAB_LABELS = {
  full: '全量產出',
  diff: '差異比對',
  baseline: '匯入Case比對',
  multi: '多規格生成'
};
const PROMPT_MODE_TEXTAREA_IDS = {
  full: 'promptFullTA',
  diff: 'promptDiffTA',
  baseline: 'promptBaselineTA',
  multi: 'promptMultiTA'
};

let savedPromptLibrary = { activeId: null, entries: [] };
let lastModePromptTab = 'full';
let savedPromptSaveTimer = null;

function newSavedPromptId() {
  return `sp_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
}

function loadSavedPromptLibrary() {
  try {
    const raw = localStorage.getItem(PROMPT_SAVED_STORAGE_KEY);
    if (!raw) return { activeId: null, entries: [] };
    const parsed = JSON.parse(raw);
    if (!parsed || !Array.isArray(parsed.entries)) return { activeId: null, entries: [] };
    return {
      activeId: parsed.activeId || parsed.entries[0]?.id || null,
      entries: parsed.entries.filter(e => e && e.id)
    };
  } catch (_) {
    return { activeId: null, entries: [] };
  }
}

function persistSavedPromptLibrary() {
  localStorage.setItem(PROMPT_SAVED_STORAGE_KEY, JSON.stringify(savedPromptLibrary));
}

function getActiveSavedEntry() {
  return savedPromptLibrary.entries.find(e => e.id === savedPromptLibrary.activeId) || null;
}

function flushSavedPromptEditor() {
  const ta = document.getElementById('promptSavedTA');
  const entry = getActiveSavedEntry();
  if (!ta || !entry) return;
  entry.content = ta.value;
  entry.updatedAt = new Date().toLocaleString('zh-TW');
  persistSavedPromptLibrary();
  updateSavedPromptMeta();
}

function updateSavedPromptMeta() {
  const meta = document.getElementById('savedPromptMeta');
  const entry = getActiveSavedEntry();
  if (!meta) return;
  meta.textContent = entry?.updatedAt
    ? `最後更新：${entry.updatedAt} · 共 ${savedPromptLibrary.entries.length} 筆`
    : `共 ${savedPromptLibrary.entries.length} 筆`;
}

function renderSavedPromptSelect() {
  const sel = document.getElementById('savedPromptSelect');
  if (!sel) return;
  sel.innerHTML = savedPromptLibrary.entries.map(e =>
    `<option value="${e.id}">${escapeHtml(e.name || '未命名')}</option>`
  ).join('');
  if (savedPromptLibrary.activeId) sel.value = savedPromptLibrary.activeId;
  updateSavedPromptInsertBtnLabel();
}

function updateSavedPromptInsertBtnLabel() {
  const btn = document.getElementById('savedPromptInsertBtn');
  if (!btn) return;
  const label = PROMPT_MODE_TAB_LABELS[lastModePromptTab] || '模式分頁';
  btn.textContent = `📥 插入到「${label}」`;
}

function loadSavedPromptIntoEditor() {
  const ta = document.getElementById('promptSavedTA');
  const entry = getActiveSavedEntry();
  if (ta) ta.value = entry?.content || '';
  updateSavedPromptMeta();
}

function ensureDefaultSavedPromptLibrary() {
  savedPromptLibrary = loadSavedPromptLibrary();
  if (!savedPromptLibrary.entries.length) {
    const id = newSavedPromptId();
    savedPromptLibrary = {
      activeId: id,
      entries: [{ id, name: '新提示詞 1', content: '', updatedAt: '' }]
    };
    persistSavedPromptLibrary();
  }
  if (!savedPromptLibrary.activeId) {
    savedPromptLibrary.activeId = savedPromptLibrary.entries[0].id;
    persistSavedPromptLibrary();
  }
}

function initSavedPromptLibrary() {
  ensureDefaultSavedPromptLibrary();
  renderSavedPromptSelect();
  loadSavedPromptIntoEditor();

  const ta = document.getElementById('promptSavedTA');
  ta?.addEventListener('input', () => {
    clearTimeout(savedPromptSaveTimer);
    savedPromptSaveTimer = setTimeout(() => flushSavedPromptEditor(), 400);
  });
  ta?.addEventListener('blur', () => flushSavedPromptEditor());

  document.getElementById('savedPromptSelect')?.addEventListener('change', (e) => {
    flushSavedPromptEditor();
    savedPromptLibrary.activeId = e.target.value;
    persistSavedPromptLibrary();
    loadSavedPromptIntoEditor();
  });

  document.getElementById('savedPromptAddBtn')?.addEventListener('click', () => {
    flushSavedPromptEditor();
    const name = prompt('新提示詞名稱：', `新提示詞 ${savedPromptLibrary.entries.length + 1}`);
    if (!name?.trim()) return;
    const id = newSavedPromptId();
    savedPromptLibrary.entries.push({
      id,
      name: name.trim(),
      content: '',
      updatedAt: ''
    });
    savedPromptLibrary.activeId = id;
    persistSavedPromptLibrary();
    renderSavedPromptSelect();
    loadSavedPromptIntoEditor();
  });

  document.getElementById('savedPromptRenameBtn')?.addEventListener('click', () => {
    const entry = getActiveSavedEntry();
    if (!entry) return;
    const name = prompt('重新命名：', entry.name);
    if (!name?.trim()) return;
    entry.name = name.trim();
    persistSavedPromptLibrary();
    renderSavedPromptSelect();
  });

  document.getElementById('savedPromptDeleteBtn')?.addEventListener('click', () => {
    if (savedPromptLibrary.entries.length <= 1) {
      alert('至少保留一筆已儲存提示詞');
      return;
    }
    const entry = getActiveSavedEntry();
    if (!entry) return;
    if (!confirm(`確定刪除「${entry.name}」？`)) return;
    savedPromptLibrary.entries = savedPromptLibrary.entries.filter(e => e.id !== entry.id);
    savedPromptLibrary.activeId = savedPromptLibrary.entries[0]?.id || null;
    persistSavedPromptLibrary();
    renderSavedPromptSelect();
    loadSavedPromptIntoEditor();
  });

  document.getElementById('savedPromptCopyBtn')?.addEventListener('click', async () => {
    flushSavedPromptEditor();
    const text = getActiveSavedEntry()?.content || '';
    if (!text.trim()) {
      alert('目前沒有內容可複製');
      return;
    }
    try {
      await navigator.clipboard.writeText(text);
      const btn = document.getElementById('savedPromptCopyBtn');
      const prev = btn.textContent;
      btn.textContent = '✅ 已複製';
      setTimeout(() => { btn.textContent = prev; }, 1200);
    } catch (_) {
      alert('複製失敗，請手動全選複製');
    }
  });

  document.getElementById('savedPromptInsertBtn')?.addEventListener('click', () => {
    flushSavedPromptEditor();
    const text = getActiveSavedEntry()?.content?.trim();
    if (!text) {
      alert('目前沒有內容可插入');
      return;
    }
    const taId = PROMPT_MODE_TEXTAREA_IDS[lastModePromptTab] || 'promptFullTA';
    const ta = document.getElementById(taId);
    if (!ta) return;
    const block = text + '\n\n';
    ta.value = ta.value.includes(text) ? ta.value : block + ta.value;
    const label = PROMPT_MODE_TAB_LABELS[lastModePromptTab] || '模式分頁';
    activatePromptTab(lastModePromptTab);
    const btn = document.getElementById('savedPromptInsertBtn');
    if (btn) {
      const prev = btn.textContent;
      btn.textContent = `✅ 已插入「${label}」`;
      setTimeout(() => updateSavedPromptInsertBtnLabel(), 1500);
    }
  });
}

let activePromptTab = 'full';

function activatePromptTab(tab) {
  if (activePromptTab === 'saved' && tab !== 'saved') {
    flushSavedPromptEditor();
  }
  if (tab !== 'saved') lastModePromptTab = tab;
  activePromptTab = tab;

  const tabs = {
    full: document.getElementById('tabFull'),
    diff: document.getElementById('tabDiff'),
    baseline: document.getElementById('tabBaseline'),
    multi: document.getElementById('tabMulti'),
    saved: document.getElementById('tabSaved')
  };
  const areas = {
    full: document.getElementById('promptFullTA'),
    diff: document.getElementById('promptDiffTA'),
    baseline: document.getElementById('promptBaselineTA'),
    multi: document.getElementById('promptMultiTA')
  };
  const savedPanel = document.getElementById('savedPromptPanel');
  const modeFooter = document.getElementById('promptModeFooter');
  const isSaved = tab === 'saved';

  Object.keys(tabs).forEach(k => {
    tabs[k]?.classList.toggle('active', k === tab);
  });
  Object.keys(areas).forEach(k => {
    if (areas[k]) areas[k].style.display = (!isSaved && k === tab) ? '' : 'none';
  });
  if (savedPanel) savedPanel.style.display = isSaved ? 'block' : 'none';
  if (modeFooter) modeFooter.style.display = isSaved ? 'none' : '';

  if (isSaved) {
    renderSavedPromptSelect();
    loadSavedPromptIntoEditor();
  }
}

// Tab 切換
document.getElementById('tabFull').addEventListener('click', () => activatePromptTab('full'));
document.getElementById('tabDiff').addEventListener('click', () => activatePromptTab('diff'));
document.getElementById('tabBaseline').addEventListener('click', () => activatePromptTab('baseline'));
document.getElementById('tabMulti')?.addEventListener('click', () => activatePromptTab('multi'));
document.getElementById('tabSaved')?.addEventListener('click', () => activatePromptTab('saved'));

// 重置為預設
document.getElementById('resetPromptBtn').addEventListener('click', () => {
  if (document.getElementById('tabSaved')?.classList.contains('active')) return;
  if (document.getElementById('tabFull').classList.contains('active')) {
    document.getElementById('promptFullTA').value = getDefaultFullTemplate();
  } else if (document.getElementById('tabDiff').classList.contains('active')) {
    document.getElementById('promptDiffTA').value = getDefaultDiffTemplate();
  } else if (document.getElementById('tabMulti')?.classList.contains('active')) {
    document.getElementById('promptMultiTA').value = getDefaultMultiTemplate();
  } else {
    document.getElementById('promptBaselineTA').value = getDefaultBaselineTemplate();
  }
});

// ─── 篩選列事件 ──────────────────────────────────────────────
['filterText', 'filterType', 'filterCat', 'filterLevel', 'filterStatus'].forEach(id => {
  const el = document.getElementById(id);
  if (!el) return;
  const onFilterChange = () => {
    if (id === 'filterText') filterPrdDoc = null;
    if (currentCases.length) refreshDisplay();
  };
  el.addEventListener('input', onFilterChange);
  if (el.tagName === 'SELECT') el.addEventListener('change', onFilterChange);
});

// ─── 排序表頭點擊 ────────────────────────────────────────────
document.querySelector('.result-table thead').addEventListener('click', e => {
  const th = e.target.closest('th[data-sort-field]');
  if (!th || !currentCases.length) return;
  const field = th.dataset.sortField;
  if (sortState.col === field) {
    if (sortState.dir === 'asc') {
      sortState.dir = 'desc';
    } else {
      sortState.col = null;   // 第三次點擊：還原原始順序
      sortState.dir = 'asc';
    }
  } else {
    sortState.col = field;
    sortState.dir = 'asc';
  }
  refreshDisplay();
});

// ─── 補填空值按鈕 ────────────────────────────────────────────
document.getElementById('refillBtn').addEventListener('click', runRefill);

// ─── 起始還原：從 IndexedDB 讀取上次儲存的案例 ──────────────
async function loadSavedCasesOnStartup() {
  try {
    const saved = await dbLoadCases();
    if (!saved || !saved.cases || saved.cases.length === 0) return;
    const banner = document.getElementById('restoreBanner');
    document.getElementById('restoreText').textContent =
      `🔄 找到上次儲存的 ${saved.count || saved.cases.length} 個案例（${saved.savedAt}），是否還原？`;
    banner.classList.add('visible');

    document.getElementById('restoreBtn').onclick = async () => {
      if (!lastNewSpecText) {
        try {
          const spec = await dbLoadSpec();
          if (spec?.text) {
            lastNewSpecText = spec.text;
            if (!lastSpecSourceFilename && spec.filename) {
              lastSpecSourceFilename = spec.filename.replace(/\s*\+.*$/, '').trim();
            }
          }
        } catch (_) {}
      }
      if (lastNewSpecText) {
        lastSpecOutline = buildSpecOutline(lastNewSpecText);
      }
      currentCases = saved.cases.map(c => normalizeCaseEntry(c, lastSpecOutline));
      currentCases = sortCasesByOutline(currentCases, lastSpecOutline);
      banner.classList.remove('visible');
      document.getElementById('resultSection').classList.add('visible');
      refreshDisplay();
    };
    document.getElementById('restoreSkipBtn').onclick = () => {
      banner.classList.remove('visible');
    };
  } catch (_) {}
}

// ─── 啟動 ────────────────────────────────────────────────────
initXlsxSheetPanelButtons();
initLlmSettings();
initPromptTextareas();
initSavedPromptLibrary();
initCoveragePanel();
initManualIndexPanel();
loadCacheOnStartup();
loadSavedCasesOnStartup();
checkReady();
