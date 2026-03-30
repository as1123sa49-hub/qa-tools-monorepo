/**
 * 測試案例自動產生工具 — 前端邏輯
 * PDF 解析 → Gemini AI → JSON 修復 → 表格顯示 → CSV 匯出
 * 功能：IndexedDB 快取舊版規格 / 附加分析模式
 */

// ─── PDF.js 設定 ────────────────────────────────────────────
pdfjsLib.GlobalWorkerOptions.workerSrc =
  'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';

// ─── 今日日期（版本標籤用）───────────────────────────────────
function getTodayStr() {
  const d = new Date();
  return d.getFullYear().toString() +
    String(d.getMonth() + 1).padStart(2, '0') +
    String(d.getDate()).padStart(2, '0');
}

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
  document.getElementById('oldZoneSub').textContent      = '舊版規格書 PDF（差異比對用）';
  document.getElementById('oldZoneOptional').textContent = '⚠ 不上傳則產出完整案例';
  checkReady();
}

async function loadCacheOnStartup() {
  try {
    const spec = await dbLoadSpec();
    if (spec) showCacheNotice(spec);
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

// ─── Prompt 模板（來自 n8n workflow）────────────────────────
const PROMPT_FULL = (specText) => `你是一位擁有 10 年經驗的資深遊戲 QA 測試專家。請針對下方【規格書內容】進行「深度邏輯掃描」，並產出結構化的測試案例。

### 核心操作原則：
1. **【排除刪除線】**：嚴禁針對有 [刪除線] 或 [中劃線] 的廢棄規則設計案例。
2. **【原子化拆解】**：嚴禁將多個驗證點寫在同一條案例中。請將每個動作與預期結果拆解到最小單位，以極大化案例數量。
3. **【精確溯源】**：每個案例必須標註對應規格書中的「頁碼」或「章節編號」，確保 100% 可追溯。

### 測試案例產出指令：
1. **全路徑與邏輯窮舉**：
    - **正面流程**：驗證完整生命週期（下注 -> 動態過程 -> 結算 -> 派彩）。
    - **負面與異常**：驗證所有限制條件（金額門檻、非法操作、網路異常、連點行為）。
    - **邊界測試**：針對文檔中出現的所有數值（賠率、金額、局數、時間）設計「剛好達標」與「越過邊界」的驗證。
    - **UI/LED 特效**：針對 LED 展示、轉場動畫、音效觸發時機設計驗證點。

2. **排序要求**：
    - 順序：[正面測試] -> [負面測試] -> [邊界測試]。
    - 類別：[大廳] -> [房內] -> [異常處理] -> [後台]。

### 輸出規範 (JSON 格式)：
- 僅回傳純 JSON 陣列，不包含 Markdown 標記，不包含說明文字。
- **每個欄位皆為必填，絕對不可省略 key 或留空字串。若無適當內容則填「無」或「—」。**
- 每個物件必須嚴格包含以下鍵值（請依此順序排列）：
    - "測試類型": [正面測試, 負面測試, 邊界測試]
    - "類別": [大廳, 房內, 異常處理, 後台]
    - "前置條件": 執行測試前需具備的狀態；若無則填「無」
    - "功能模組": 必填，具體功能點（如「派彩計算」、「倍數觸發」），不可空白
    - "規格來源": 必填，規格書的頁碼或章節（如「第 5 頁」、「§3.2」、「第 1.b 節」）。嚴禁填寫本指令自身的編號（如「1.a」、「2.b」）
    - "測試標題": 必填，[動作] + [情境/條件]，不可空白
    - "預期結果": 必填，簡練判斷標準（30字內），不可空白
    - "影響層級": [P0, P1, P2] 三選一，不附加任何括號說明文字
    - "編號": 類型縮寫_類別縮寫_序號（如 POS_ROOM_001）
    - "版本標籤": "${getTodayStr()}_v1"

### 參考來源：
${specText}`;

const PROMPT_DIFF = (newSpecText, oldSpecText) => `你是一位擁有 10 年經驗的資深遊戲 QA 測試專家。請針對下方提供的【舊版規格】與【新版規格】進行「差異增量掃描」，並僅針對「變動或新增」的邏輯產出結構化測試案例。

### 數據來源：
- 【舊版規格內容(比對基準)】：${oldSpecText}
- 【新版規格內容(本次更新)】：${newSpecText}

### 增量比對原則：
1. **僅針對差異產出**：對比兩份規格，若功能點、數值、描述完全無變動，則不產出案例。僅針對「新增功能」、「修改規則/數值」、「修復邏輯」進行設計。
2. **追蹤變更**：在「功能模組」欄位中，必須加註 [新增] 或 [變更] 字樣。

### 核心操作原則（嚴格遵守）：
1. **【排除刪除線】**：嚴禁針對有 [刪除線] 或 [中劃線] 的廢棄規則設計案例。
2. **【原子化拆解】**：每個物件僅包含單一驗證點。
3. **【精確溯源】**：必須標註對應「新版規格書」中的頁碼或章節編號。

### 測試案例排序要求：
1. 類型順序：[正面測試] -> [負面測試] -> [邊界測試]
2. 類別順序：[大廳] -> [房內] -> [異常處理] -> [後台]

### 輸出規範 (JSON 格式)：
- 僅回傳純 JSON 陣列，不包含 Markdown 標記，不包含說明文字。
- **每個欄位皆為必填，絕對不可省略 key 或留空字串。若無適當內容則填「無」或「—」。**
- 每個物件必須嚴格包含以下鍵值（請依此順序排列）：
    - "測試類型": [正面測試, 負面測試, 邊界測試]
    - "類別": [大廳, 房內, 異常處理, 後台]
    - "前置條件": 執行測試前需具備的狀態；若無則填「無」
    - "功能模組": 必填，具體功能點（含 [新增] 或 [變更] 標注），不可空白
    - "規格來源": 必填，新版規格書的頁碼或章節（如「第 5 頁」、「§3.2」）。嚴禁填寫本指令自身的編號（如「1.a」、「2.b」）
    - "測試標題": 必填，[動作] + [情境/條件]，不可空白
    - "預期結果": 必填，簡練判斷標準（30字內），不可空白
    - "影響層級": [P0, P1, P2] 三選一，不附加任何括號說明文字
    - "編號": 類型縮寫_類別縮寫_序號（如 POS_ROOM_001）
    - "版本標籤": "${getTodayStr()}_v1"`;

// ─── Prompt：驗證舊案例有效性 ────────────────────────────────
const PROMPT_OBSOLETE = (newSpecText, caseSummaryJson, newCaseSummaryJson) =>
`你是一位資深遊戲 QA 測試專家。請根據【新版規格書】審查【現有測試案例清單】，找出哪些案例已不符合新版規格（功能已移除、規則或數值已更改、條件已不適用等）。
同時，若某個失效案例在【新增案例清單】中有功能相近的新案例，請填入其編號作為「取代者」。

【新版規格書】：
${newSpecText}

【現有測試案例清單（JSON）】：
${caseSummaryJson}

【新增案例清單（JSON）】：
${newCaseSummaryJson}

### 輸出規範：
- 僅回傳 JSON 物件陣列，每個物件包含：
  - "編號": 失效的舊案例編號（字串）
  - "取代者": 新增案例中功能相近的編號（字串），若無對應則填 null
- 若所有案例仍有效，回傳空陣列：[]
- 範例：[{"編號":"NEG_ROOM_001","取代者":"NEG_ROOM_012"},{"編號":"POS_LOB_003","取代者":null}]
- 不包含 Markdown 標記，不包含任何說明文字`;

// ─── 失效案例驗證（Step V）────────────────────────────────────
async function runObsoleteCheck(apiKey, newText, existingCases, newCases) {
  const toSummary = arr => arr.map(c => ({
    編號: c['編號'], 功能模組: c['功能模組'],
    測試標題: c['測試標題'], 預期結果: c['預期結果']
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
    const raw = await callGemini(apiKey,
      PROMPT_OBSOLETE(newText, JSON.stringify(summary, null, 2), JSON.stringify(newSummary, null, 2))
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
function fixTruncatedJson(jsonString) {
  try {
    JSON.parse(jsonString);
    return jsonString;
  } catch (_) {
    const lastOpenBrace = jsonString.lastIndexOf('{');
    if (lastOpenBrace === -1) return '[]';

    let fixed = jsonString.substring(0, lastOpenBrace).trim();
    if (fixed.endsWith(',')) fixed = fixed.slice(0, -1);
    fixed += '\n]';

    try {
      JSON.parse(fixed);
      return fixed;
    } catch (_) {
      return fixed.replace(/,$/, '') + ']';
    }
  }
}

// ─── PDF 文字提取 ────────────────────────────────────────────
async function extractPdfText(file) {
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

// ─── Gemini API 呼叫 ─────────────────────────────────────────
async function callGemini(apiKey, prompt) {
  const res = await fetch(
    `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key=${apiKey}`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        contents: [{ parts: [{ text: prompt }] }],
        generationConfig: { responseMimeType: 'application/json' }
      })
    }
  );
  const data = await res.json();
  if (!res.ok) throw new Error(data.error?.message || `API 錯誤 (${res.status})`);

  const part = data.candidates?.[0]?.content?.parts?.[0];
  if (!part) throw new Error('AI 回傳格式異常，找不到輸出內容');
  return part.text || '';
}

// ─── 解析 AI 回傳的 JSON ─────────────────────────────────────
function parseAiJson(rawText) {
  let cleaned = rawText.replace(/```json|```/g, '').trim();
  const safeText = fixTruncatedJson(cleaned);
  const parsed = JSON.parse(safeText);
  if (!Array.isArray(parsed)) throw new Error('AI 回傳的不是陣列');
  return parsed.map(entry => {
    // 影響層級：去除括號說明文字（"P0 (核心邏輯)" → "P0"）
    const rawLevel = entry['影響層級'] || entry['層級'] || entry['priority'] || '';
    const level = rawLevel.replace(/\s*[\(（][^)）]*[\)）]/g, '').trim();

    // 規格來源：偵測裸格式幻覺（如 "1.b"、"2.a"）
    const rawSrc = entry['規格來源'] || entry['來源'] || entry['spec_source'] || '';
    const srcSuspicious = rawSrc.trim() !== '' && /^\d+\.[a-zA-Z]$/.test(rawSrc.trim());

    return {
      '測試類型':    entry['測試類型'] || '',
      '類別':        entry['類別']     || '',
      '前置條件':    entry['前置條件'] || '',
      '功能模組':    entry['功能模組'] || entry['模組'] || entry['功能'] || entry['function_module'] || '',
      '規格來源':    rawSrc,
      '_srcSuspicious': srcSuspicious,
      '測試標題':    entry['測試標題'] || entry['標題'] || entry['title'] || '',
      '預期結果':    entry['預期結果'] || entry['結果'] || entry['expected'] || '',
      '影響層級':    level,
      '編號':        entry['編號']     || entry['id'] || entry['case_id'] || '',
      '版本標籤':    entry['版本標籤'] || entry['版本'] || entry['version'] || ''
    };
  });
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
  if (v.includes('大廳'))   return `<span class="tag tag-hall">大廳</span>`;
  if (v.includes('房內'))   return `<span class="tag tag-room">房內</span>`;
  if (v.includes('異常'))   return `<span class="tag tag-err">異常</span>`;
  if (v.includes('後台'))   return `<span class="tag tag-admin">後台</span>`;
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

const EMPTY_CHECK_FIELDS = ['功能模組', '測試標題', '預期結果', '規格來源'];

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
    if (c['_obsolete']) obsoleteCount++;
  });

  // 渲染列（filtered+sorted cases）
  cases.forEach(c => {
    const isObsolete = !!c['_obsolete'];

    const repCell = isObsolete
      ? (c['_replacedBy']
          ? `<td class="col-rep"><span class="case-link" onclick="scrollToCase('${c['_replacedBy']}')">${c['_replacedBy']}</span></td>`
          : `<td class="col-rep" style="color:var(--muted);font-size:11px;">已廢除</td>`)
      : `<td class="col-rep"></td>`;

    const tr = document.createElement('tr');
    if (isObsolete) tr.classList.add('row-obsolete');
    if (c['編號']) tr.setAttribute('data-case-id', c['編號']);
    tr.innerHTML = `
      <td class="col-status">${isObsolete ? '❌ 失效' : '✅ 有效'}</td>
      ${repCell}
      <td class="col-no">${c['編號'] || '<span class="cell-empty">—</span>'}</td>
      <td class="col-type">${typeTag(c['測試類型'])}</td>
      <td class="col-cat">${catTag(c['類別'])}</td>
      <td class="col-lvl">${lvlTag(c['影響層級'])}</td>
      ${cellOrEmpty(c['功能模組'], 'col-mod')}
      ${cellOrEmpty(c['前置條件'], 'col-pre')}
      ${cellOrEmpty(c['測試標題'], 'col-title')}
      ${cellOrEmpty(c['預期結果'], 'col-exp')}
      ${cellOrEmpty(c['規格來源'], 'col-src', c['_srcSuspicious'])}
      <td class="col-ver">${c['版本標籤'] || ''}</td>
    `;
    tbody.appendChild(tr);
  });
  document.getElementById('caseCount').textContent = allCases.length;

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

// ─── 全域狀態 ────────────────────────────────────────────────
let currentCases    = [];
let sortState       = { col: null, dir: 'asc' };
let lastNewSpecText = null;   // 供「補填空值」功能使用

// ─── 篩選邏輯 ────────────────────────────────────────────────
function filterCases(cases) {
  const text   = (document.getElementById('filterText')?.value   || '').toLowerCase().trim();
  const type   =  document.getElementById('filterType')?.value   || '';
  const cat    =  document.getElementById('filterCat')?.value    || '';
  const level  =  document.getElementById('filterLevel')?.value  || '';
  const status =  document.getElementById('filterStatus')?.value || '';

  return cases.filter(c => {
    if (type   && !(c['測試類型'] || '').includes(type))  return false;
    if (cat    && !(c['類別']     || '').includes(cat))   return false;
    if (level  && !(c['影響層級'] || '').includes(level)) return false;
    if (status === 'valid'   &&  c['_obsolete'])  return false;
    if (status === 'obsolete' && !c['_obsolete']) return false;
    if (text) {
      const haystack = [c['編號'], c['測試標題'], c['功能模組'], c['預期結果'], c['類別']]
        .map(v => v || '').join(' ').toLowerCase();
      if (!haystack.includes(text)) return false;
    }
    return true;
  });
}

// ─── 排序邏輯 ────────────────────────────────────────────────
function sortCases(cases) {
  if (!sortState.col) return [...cases];
  const LVL_ORDER = { 'P0': 0, 'P1': 1, 'P2': 2 };
  return [...cases].sort((a, b) => {
    if (sortState.col === '影響層級') {
      const va = LVL_ORDER[a['影響層級']] ?? 9;
      const vb = LVL_ORDER[b['影響層級']] ?? 9;
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
  const el = document.getElementById('caseBreakdown');
  if (!el || currentCases.length === 0) {
    if (el) el.textContent = '';
    return;
  }
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
  const filtered = filterCases(currentCases);
  const sorted   = sortCases(filtered);

  // 篩選計數提示
  const countEl = document.getElementById('filterCount');
  if (countEl) {
    countEl.textContent = filtered.length < currentCases.length
      ? `篩選 ${filtered.length} / ${currentCases.length} 筆`
      : '';
  }

  renderTable(sorted, currentCases);   // 渲染已篩選列，統計來自全部
  updateBreakdown();
  updateRefillBtn();
  updateSortHeaders();
  checkReady();  // 更新前綴必填狀態

  // 非同步自動儲存（fire & forget）
  if (currentCases.length > 0) dbSaveCases(currentCases).catch(() => {});
}

// ─── Prompt：補填空值欄位 ────────────────────────────────────
const PROMPT_REFILL = (incompleteCasesJson, specText) =>
`你是一位資深遊戲 QA 測試專家。以下是部分欄位為空的測試案例，請根據【規格書內容】補全缺少的欄位。

【需補全的案例（JSON）】：
${incompleteCasesJson}

【規格書內容】：
${specText}

### 輸出規範：
- 回傳完整的 JSON 陣列，每個物件保留原有「編號」不變
- 僅補全空白欄位，非空欄位原樣保留
- 每個欄位皆為必填，根據測試標題和規格內容合理推斷；若實在無法判斷，填「—」
- "功能模組"：具體功能點，不可空白
- "規格來源"：規格書頁碼或章節（如「第 5 頁」），嚴禁填寫指令編號（如「1.a」）
- "影響層級"：[P0, P1, P2] 三選一，不加括號說明
- 不包含 Markdown 標記，不包含任何說明文字`;

// ─── 補填空值案例 ────────────────────────────────────────────
async function runRefill() {
  const apiKey = document.getElementById('apiKeyInput').value.trim();
  if (!apiKey)          { alert('請先填入 Gemini API Key'); return; }
  if (!lastNewSpecText) { alert('請先執行一次完整分析，以載入規格書文字'); return; }

  const emptyCases = currentCases.filter(c =>
    EMPTY_CHECK_FIELDS.some(f => !c[f] || c[f].trim() === '')
  );
  if (emptyCases.length === 0) return;

  const btn = document.getElementById('refillBtn');
  btn.disabled = true;
  btn.textContent = '⏳ 補填中...';

  try {
    const summary = emptyCases.map(c => ({
      '編號':    c['編號']    || '',
      '功能模組': c['功能模組'] || '',
      '前置條件': c['前置條件'] || '',
      '測試標題': c['測試標題'] || '',
      '預期結果': c['預期結果'] || '',
      '規格來源': c['規格來源'] || '',
      '影響層級': c['影響層級'] || '',
    }));

    const raw     = await callGemini(apiKey, PROMPT_REFILL(JSON.stringify(summary, null, 2), lastNewSpecText));
    const cleaned = raw.replace(/```json|```/g, '').trim();
    const refilled = JSON.parse(cleaned);

    if (Array.isArray(refilled)) {
      const refillMap = new Map(refilled.map(r => [r['編號'], r]));
      currentCases = currentCases.map(c => {
        const r = refillMap.get(c['編號']);
        if (!r) return c;
        return {
          ...c,
          '功能模組': c['功能模組'] || r['功能模組'] || '',
          '前置條件': c['前置條件'] || r['前置條件'] || '',
          '測試標題': c['測試標題'] || r['測試標題'] || '',
          '預期結果': c['預期結果'] || r['預期結果'] || '',
          '規格來源': c['規格來源'] || r['規格來源'] || '',
          '影響層級': c['影響層級'] || r['影響層級'] || '',
        };
      });
      refreshDisplay();
    }
  } catch (err) {
    alert('補填失敗：' + err.message);
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
    { header: '影響層級', key: 'level',    width: 10 },
    { header: '功能模組', key: 'module',   width: 28 },
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
    const isObsolete = !!c['_obsolete'];
    const row = ws.addRow({
      status:    isObsolete ? '已失效（僅供參考）' : '有效',
      replacedBy: c['_replacedBy'] || '',
      id:        c['編號']   || '',
      type:      c['測試類型'] || '',
      cat:       c['類別']   || '',
      level:     c['影響層級'] || '',
      module:    c['功能模組'] || '',
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
    const fieldMap = { '功能模組':'module', '測試標題':'title', '預期結果':'expected', '規格來源':'src' };
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

  const apiKey  = document.getElementById('apiKeyInput').value.trim();
  const newFile = document.getElementById('newFile').files[0];
  const oldFile = document.getElementById('oldFile').files[0];

  if (!apiKey)  { showError('請填入 Gemini API Key'); return; }
  if (!newFile) { showError('請上傳新版規格書 PDF'); return; }

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
  if (!appendMode) document.getElementById('resultSection').classList.remove('visible');
  document.getElementById('analyzeBtn').disabled = true;

  try {
    // Step 1：解析 PDF
    setStep(1, 'running');
    document.getElementById('step1Text').textContent = `解析 PDF 文字...`;

    const newText = await extractPdfText(newFile);
    lastNewSpecText = newText;   // 供補填功能使用

    // 決定舊版文字來源：上傳的檔案 > 快取 > 無
    let oldText     = null;
    let oldLabel    = '';
    if (oldFile) {
      oldText  = await extractPdfText(oldFile);
      oldLabel = oldFile.name;
    } else if (useCache && cachedSpec) {
      oldText  = cachedSpec.text;
      oldLabel = `${cachedSpec.filename}（快取）`;
    }

    setStep(1, 'done');
    document.getElementById('step1Text').textContent =
      `PDF 解析完成（新版 ${newFile.name}${oldText ? '，舊版 ' + oldLabel : ''}）`;

    // Step 2：呼叫 Gemini AI（含進度條）
    setStep(2, 'running');
    const mode = oldText ? '差異比對模式' : '全量產出模式';
    document.getElementById('step2Text').textContent = `呼叫 Gemini AI（${mode}）...`;

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
      const prompt = oldText ? buildDiffPrompt(newText, oldText) : buildFullPrompt(newText);
      rawText = await callGemini(apiKey, prompt);
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

    const rawCases     = parseAiJson(rawText);
    const versionPrefix = document.getElementById('verPrefixInput').value.trim();

    // 差異比對 + 附加模式 + 有前綴 → 新案例編號加前綴
    const newCases = (versionPrefix && oldText && appendMode)
      ? rawCases.map(c => ({ ...c, '編號': c['編號'] ? `${versionPrefix}_${c['編號']}` : c['編號'] }))
      : rawCases;

    if (appendMode) {
      currentCases = [...currentCases, ...newCases];
    } else {
      currentCases = newCases;
    }

    setStep(3, 'done');
    document.getElementById('step3Text').textContent =
      appendMode
        ? `附加完成！目前共 ${currentCases.length} 個測試案例（本次新增 ${newCases.length} 個）`
        : `完成！共產出 ${currentCases.length} 個測試案例`;

    refreshDisplay();
    document.getElementById('resultSection').classList.add('visible');

    // ── Step V：附加模式 + 有舊版規格 → 驗證既有案例有效性 ──────
    if (appendMode && oldText) {
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
      await dbSaveSpec(newFile.name, newText);
      const spec = { filename: newFile.name, text: newText, savedAt: new Date().toLocaleString('zh-TW') };
      showCacheNotice(spec);
      // 若剛才是以舊快取做比對，清除 useCache 狀態（已完成本次比對）
      if (useCache) deactivateCache();
    } catch (_) {}

  } catch (err) {
    const step = [1, 2, 3].find(n =>
      document.getElementById(`step${n}Icon`).classList.contains('running')
    ) || 1;
    setStep(step, 'error');
    showError(err.message);
  } finally {
    document.getElementById('analyzeBtn').disabled = false;
  }
}

// ─── API Key 管理 ────────────────────────────────────────────
function loadApiKey() {
  const saved = localStorage.getItem('gemini_api_key');
  if (saved) document.getElementById('apiKeyInput').value = saved;
}

document.getElementById('saveKeyBtn').addEventListener('click', () => {
  const key = document.getElementById('apiKeyInput').value.trim();
  if (!key) { alert('請先輸入 API Key'); return; }
  localStorage.setItem('gemini_api_key', key);
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

// ─── 檔案上傳 UI ─────────────────────────────────────────────
function setupFileZone(fileInputId, zoneId, fileNameId) {
  const input = document.getElementById(fileInputId);
  const zone  = document.getElementById(zoneId);
  const label = document.getElementById(fileNameId);

  input.addEventListener('change', () => {
    const file = input.files[0];
    if (file) {
      label.textContent = `📎 ${file.name}`;
      zone.classList.add('has-file');
      // 上傳檔案到舊版區時，取消快取模式
      if (fileInputId === 'oldFile' && useCache) deactivateCache();
      checkReady();
    }
  });

  zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('drag-over'); });
  zone.addEventListener('dragleave', () => zone.classList.remove('drag-over'));
  zone.addEventListener('drop', e => {
    e.preventDefault();
    zone.classList.remove('drag-over');
    const file = e.dataTransfer.files[0];
    if (file && file.type === 'application/pdf') {
      const dt = new DataTransfer();
      dt.items.add(file);
      input.files = dt.files;
      label.textContent = `📎 ${file.name}`;
      zone.classList.add('has-file');
      if (fileInputId === 'oldFile' && useCache) deactivateCache();
      checkReady();
    }
  });
}

// ─── 版本前綴輔助 ────────────────────────────────────────────
function hasOldSpec() {
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
  const required   = isPrefixRequired();
  const hasPrefix  = document.getElementById('verPrefixInput').value.trim().length > 0;
  document.getElementById('analyzeBtn').disabled = !(hasApiKey && hasNewFile && (!required || hasPrefix));
  updatePrefixUI();
}

document.getElementById('apiKeyInput').addEventListener('input', checkReady);
document.getElementById('verPrefixInput').addEventListener('input', checkReady);

setupFileZone('newFile', 'newZone', 'newFileName');
setupFileZone('oldFile', 'oldZone', 'oldFileName');

document.getElementById('analyzeBtn').addEventListener('click', runAnalysis);

document.getElementById('exportCsvBtn').addEventListener('click', async () => {
  if (currentCases.length > 0) {
    const btn = document.getElementById('exportCsvBtn');
    btn.disabled = true;
    btn.textContent = '⏳ 產生中...';
    try {
      await downloadXLSX(currentCases);
    } finally {
      btn.disabled = false;
      btn.textContent = '📊 匯出 XLSX';
    }
  }
});

document.getElementById('reAnalyzeBtn').addEventListener('click', () => {
  document.getElementById('resultSection').classList.remove('visible');
  document.getElementById('statusPanel').classList.remove('visible');
  document.getElementById('stepV').style.display = 'none';
  document.getElementById('removeObsoleteBtn').style.display = 'none';
  document.getElementById('refillBtn').style.display = 'none';
  clearError();
  currentCases = [];
  lastNewSpecText = null;
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

function buildFullPrompt(newText) {
  const tpl = document.getElementById('promptFullTA').value;
  return tpl.replace('{{SPEC}}', newText);
}
function buildDiffPrompt(newText, oldText) {
  return document.getElementById('promptDiffTA').value
    .replace('{{NEW_SPEC}}', newText)
    .replace('{{OLD_SPEC}}', oldText);
}

function initPromptTextareas() {
  document.getElementById('promptFullTA').value = getDefaultFullTemplate();
  document.getElementById('promptDiffTA').value = getDefaultDiffTemplate();
}

// Tab 切換
document.getElementById('tabFull').addEventListener('click', () => {
  document.getElementById('tabFull').classList.add('active');
  document.getElementById('tabDiff').classList.remove('active');
  document.getElementById('promptFullTA').style.display = '';
  document.getElementById('promptDiffTA').style.display = 'none';
});
document.getElementById('tabDiff').addEventListener('click', () => {
  document.getElementById('tabDiff').classList.add('active');
  document.getElementById('tabFull').classList.remove('active');
  document.getElementById('promptDiffTA').style.display = '';
  document.getElementById('promptFullTA').style.display = 'none';
});

// 重置為預設
document.getElementById('resetPromptBtn').addEventListener('click', () => {
  const isFullActive = document.getElementById('tabFull').classList.contains('active');
  if (isFullActive) {
    document.getElementById('promptFullTA').value = getDefaultFullTemplate();
  } else {
    document.getElementById('promptDiffTA').value = getDefaultDiffTemplate();
  }
});

// ─── 篩選列事件 ──────────────────────────────────────────────
['filterText', 'filterType', 'filterCat', 'filterLevel', 'filterStatus'].forEach(id => {
  const el = document.getElementById(id);
  if (el) el.addEventListener('input', () => { if (currentCases.length) refreshDisplay(); });
});

// ─── 排序表頭點擊 ────────────────────────────────────────────
document.querySelector('.result-table thead').addEventListener('click', e => {
  const th = e.target.closest('th[data-sort-field]');
  if (!th || !currentCases.length) return;
  const field = th.dataset.sortField;
  if (sortState.col === field) {
    sortState.dir = sortState.dir === 'asc' ? 'desc' : 'asc';
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

    document.getElementById('restoreBtn').onclick = () => {
      currentCases = saved.cases;
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
loadApiKey();
initPromptTextareas();
loadCacheOnStartup();
loadSavedCasesOnStartup();
checkReady();
