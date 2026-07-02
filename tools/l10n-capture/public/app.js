import {
  PROVIDER_GEMINI,
  PROVIDER_SIRAYA,
  LLM_PROVIDER_STORAGE_KEY,
  getApiKeyStorageKey,
  getApiKeyLabel,
  getModelStorageKey,
  getModelsForProvider,
  getSelectedModelId,
  renderModelOptions,
} from './llm.js';

function slotToSheet(slotId) {
  const m = String(slotId || '').trim().match(/^Slot(\d+)$/i);
  if (!m) return null;
  return `S${m[1]}`;
}

function sheetToSlot(sheetName) {
  const m = String(sheetName || '').trim().match(/^S(\d+)$/i);
  if (!m) return null;
  return `Slot${m[1]}`;
}

async function parseXlsxMeta(file) {
  const wb = new window.ExcelJS.Workbook();
  await wb.xlsx.load(await file.arrayBuffer());
  const sheets = wb.worksheets.map(ws => {
    let rowCount = 0;
    ws.eachRow({ includeEmpty: false }, () => { rowCount++; });
    return { name: ws.name, rowCount };
  });
  const langByCode = new Map();
  for (const ws of wb.worksheets) {
    const headerRow = ws.getRow(1);
    if (!headerRow) continue;
    headerRow.eachCell({ includeEmpty: true }, cell => {
      const col = parseLangColumn(safeCellText(cell));
      if (col && !langByCode.has(col.code)) langByCode.set(col.code, col);
    });
  }
  const langs = [...langByCode.values()].sort((a, b) => a.code.localeCompare(b.code));
  return { sheets, langs };
}

function safeCellText(cell) {
  if (!cell || cell.value == null) return '';
  const v = cell.value;
  if (typeof v === 'object') {
    if (Array.isArray(v.richText)) return v.richText.map(rt => rt.text || '').join('');
    if (v.text != null) return String(v.text);
    if (v.result != null) return String(v.result);
  }
  return String(v);
}

function parseLangFromHeader(header) {
  const h = String(header || '').trim();
  if (!h || h.toLowerCase() === 'key') return null;
  const m = h.match(/\(([^)]+)\)\s*$/);
  return m ? m[1].trim() : null;
}

function parseLangColumn(header) {
  const code = parseLangFromHeader(header);
  if (!code) return null;
  const h = String(header || '').trim();
  const label = h.replace(/\([^)]+\)\s*$/, '').trim() || code;
  return { code, header: h, label };
}

const dropZone = document.getElementById('dropZone');
const fileInput = document.getElementById('fileInput');
const fileInfo = document.getElementById('fileInfo');
const sheetList = document.getElementById('sheetList');
const startBtn = document.getElementById('startBtn');
const logBox = document.getElementById('logBox');
const slotsInput = document.getElementById('slotsInput');
const envSelect = document.getElementById('envSelect');
const langSelect = document.getElementById('langSelect');
const apiKeyInput = document.getElementById('apiKeyInput');
const apiKeyLabel = document.getElementById('apiKeyLabel');
const llmProviderSelect = document.getElementById('llmProviderSelect');
const modelSelect = document.getElementById('modelSelect');
const verifyBtn = document.getElementById('verifyBtn');
const exportBtn = document.getElementById('exportBtn');
const forceOcrToggle = document.getElementById('forceOcrToggle');
const resultCard = document.getElementById('resultCard');
const resultTabsBar = document.getElementById('resultTabs');
const resultArea = document.getElementById('resultArea');
const manualBar = document.getElementById('manualBar');
const manualStatus = document.getElementById('manualStatus');
const reverifyPasteBtn = document.getElementById('reverifyPasteBtn');

const LANG_STORAGE_KEY = 'l10n_capture_lang';
const SESSION_LOGS_KEY = 'l10n_capture_session_logs';
const SESSION_REPORTS_KEY = 'l10n_capture_session_reports';
const SESSION_REPORT_TAB_KEY = 'l10n_capture_session_report_tab';
const SESSION_SLOTS_KEY = 'l10n_capture_session_slots';
const SESSION_ENV_KEY = 'l10n_capture_session_env';
const SESSION_XLSX_KEY = 'l10n_capture_session_xlsx';
const MAX_XLSX_SESSION_BYTES = 6 * 1024 * 1024;

let xlsxFile = null;
let selectedSheets = new Set();
let sheets = [];
let xlsxLangs = [];
let langMap = {};
let lastReports = [];
let activeReportTab = 0;
/** @type {null | 'PASS' | 'REVIEW' | 'FAIL'} */
let statusFilter = null;
let previewItems = [];
let previewIndex = -1;
/** @type {string | null} */
let selectedKey = null;
let manualPasteBusy = false;
let reocrBusy = false;
/** @type {Map<string, Blob>} */
const manualImageBlobs = new Map();
/** @type {Map<string, string>} */
const manualImageUrls = new Map();

function manualRowId(rep, key) {
  return `${rep.slotId}|${rep.lang || ''}|${key}`;
}

function getManualImageUrl(rep, row) {
  return manualImageUrls.get(manualRowId(rep, row.key)) || '';
}

function revokeManualImage(rep, key) {
  const id = manualRowId(rep, key);
  const url = manualImageUrls.get(id);
  if (url) URL.revokeObjectURL(url);
  manualImageUrls.delete(id);
  manualImageBlobs.delete(id);
}

function attachManualImage(rep, key, blob, force = false) {
  const id = manualRowId(rep, key);
  if (manualImageBlobs.has(id) && !force) {
    const ok = confirm('此列已有手動截圖，確定要覆蓋嗎？');
    if (!ok) return false;
  }
  revokeManualImage(rep, key);
  manualImageBlobs.set(id, blob);
  manualImageUrls.set(id, URL.createObjectURL(blob));
  return true;
}

function recomputeSummary(results) {
  return results.reduce(
    (acc, r) => {
      acc[r.status] = (acc[r.status] || 0) + 1;
      return acc;
    },
    { PASS: 0, REVIEW: 0, FAIL: 0 },
  );
}

function mergeResultRow(rep, newRow) {
  const idx = rep.results.findIndex(r => r.key === newRow.key);
  if (idx < 0) return;
  rep.results[idx] = { ...newRow, expected: rep.results[idx].expected };
  rep.summary = recomputeSummary(rep.results);
}

function updateManualBar() {
  if (!lastReports.length) {
    manualBar.hidden = true;
    return;
  }
  manualBar.hidden = false;
  const rep = lastReports[activeReportTab];
  const row = selectedKey ? rep?.results?.find(r => r.key === selectedKey) : null;
  if (row) {
    const hasImg = manualImageBlobs.has(manualRowId(rep, selectedKey));
    const busy = manualPasteBusy ? '（比對中…）' : '';
    manualStatus.innerHTML =
      `已選取 <span class="manual-key">${escapeHtml(selectedKey)}</span> — 截圖後 <strong>Ctrl+V</strong> 貼上比對${hasImg ? '（可覆蓋重貼）' : ''}${busy}`;
    reverifyPasteBtn.disabled = !hasImg || manualPasteBusy || !apiKeyInput.value.trim();
  } else {
    manualStatus.textContent = '選取下方列後，在遊戲畫面截圖並 Ctrl+V 貼上比對';
    reverifyPasteBtn.disabled = true;
  }
}

async function runPasteVerify(rep, key, blob) {
  const row = rep.results?.find(r => r.key === key);
  if (!row || !blob) return;

  const apiKey = apiKeyInput.value.trim();
  if (!apiKey) {
    alert(`請先輸入 ${getApiKeyLabel(getLlmProvider())}`);
    return;
  }

  manualPasteBusy = true;
  updateManualBar();
  reverifyPasteBtn.disabled = true;

  try {
    const imageBase64 = arrayBufferToBase64(await blob.arrayBuffer());
    const res = await fetch('/api/verify-paste', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        key,
        expectedText: row.expected,
        imageBase64,
        mimeType: blob.type || 'image/png',
        provider: getLlmProvider(),
        apiKey,
        modelId: modelSelect.value,
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);

    mergeResultRow(rep, data.result);
    const tu = data.tokenUsage;
    const tokenPart = tu?.totalTokens
      ? ` · token ${tu.promptTokens} in / ${tu.completionTokens} out`
      : '';
    appendLog(
      `手動比對 ${rep.slotId} / ${key} → ${data.result.status} ${(data.result.similarity * 100).toFixed(0)}%${tokenPart}`,
      data.result.status === 'PASS' ? 'log-ok' : '',
    );
    persistSessionReports();
    renderReports();
  } catch (err) {
    appendLog(`手動比對失敗 ${key}：${err.message}`, 'log-err');
  } finally {
    manualPasteBusy = false;
    updateManualBar();
  }
}

function getLlmProvider() {
  const v = llmProviderSelect.value?.trim();
  return v === PROVIDER_SIRAYA ? PROVIDER_SIRAYA : PROVIDER_GEMINI;
}

function syncLlmUi({ saveKey = false } = {}) {
  const provider = getLlmProvider();
  apiKeyLabel.textContent = `${getApiKeyLabel(provider)}（儲存於本機）`;
  apiKeyInput.placeholder = provider === PROVIDER_SIRAYA ? 'sk-...' : 'AIzaSy...';
  apiKeyInput.value = localStorage.getItem(getApiKeyStorageKey(provider)) || '';

  const models = getModelsForProvider(provider);
  modelSelect.innerHTML = renderModelOptions(models);
  const modelId = getSelectedModelId(provider, modelSelect);
  modelSelect.value = modelId;
  localStorage.setItem(getModelStorageKey(provider), modelId);

  if (saveKey) {
    localStorage.setItem(getApiKeyStorageKey(provider), apiKeyInput.value.trim());
    localStorage.setItem(getModelStorageKey(provider), modelSelect.value);
  }
  updateStartBtn();
}

llmProviderSelect.addEventListener('change', () => {
  localStorage.setItem(LLM_PROVIDER_STORAGE_KEY, llmProviderSelect.value);
  syncLlmUi();
});
apiKeyInput.addEventListener('input', () => {
  localStorage.setItem(getApiKeyStorageKey(getLlmProvider()), apiKeyInput.value.trim());
  updateStartBtn();
});
modelSelect.addEventListener('change', () => {
  localStorage.setItem(getModelStorageKey(getLlmProvider()), modelSelect.value);
});

const savedProvider = localStorage.getItem(LLM_PROVIDER_STORAGE_KEY);
if (savedProvider === PROVIDER_GEMINI || savedProvider === PROVIDER_SIRAYA) {
  llmProviderSelect.value = savedProvider;
}
syncLlmUi();

function persistSessionLogs() {
  const lines = [...logBox.children].map(el => ({
    text: el.textContent || '',
    cls: el.className || '',
  }));
  try {
    sessionStorage.setItem(SESSION_LOGS_KEY, JSON.stringify(lines));
  } catch { /* quota */ }
}

function restoreSessionLogs() {
  try {
    const raw = sessionStorage.getItem(SESSION_LOGS_KEY);
    if (!raw) return;
    const lines = JSON.parse(raw);
    if (!Array.isArray(lines) || !lines.length) return;
    logBox.innerHTML = '';
    for (const { text, cls } of lines) {
      const line = document.createElement('div');
      if (cls) line.className = cls;
      line.textContent = text;
      logBox.appendChild(line);
    }
    logBox.scrollTop = logBox.scrollHeight;
  } catch { /* ignore */ }
}

function persistSessionReports() {
  try {
    sessionStorage.setItem(SESSION_REPORTS_KEY, JSON.stringify(lastReports));
    sessionStorage.setItem(SESSION_REPORT_TAB_KEY, String(activeReportTab));
  } catch { /* quota */ }
}

function restoreSessionReports() {
  try {
    const raw = sessionStorage.getItem(SESSION_REPORTS_KEY);
    if (!raw) return;
    const reports = JSON.parse(raw);
    if (!Array.isArray(reports) || !reports.length) return;
    lastReports = reports;
    const tab = Number(sessionStorage.getItem(SESSION_REPORT_TAB_KEY) || 0);
    activeReportTab = Number.isFinite(tab) ? tab : 0;
    renderReports();
    exportBtn.disabled = false;
  } catch { /* ignore */ }
}

function persistSessionSlots() {
  try {
    sessionStorage.setItem(SESSION_SLOTS_KEY, slotsInput.value.trim());
    sessionStorage.setItem(SESSION_ENV_KEY, envSelect.value);
  } catch { /* quota */ }
}

function restoreSessionSlots() {
  try {
    const slots = sessionStorage.getItem(SESSION_SLOTS_KEY);
    if (slots) slotsInput.value = slots;
    const env = sessionStorage.getItem(SESSION_ENV_KEY);
    if (env && [...envSelect.options].some(o => o.value === env)) {
      envSelect.value = env;
    }
  } catch { /* ignore */ }
}

function clearSessionState() {
  sessionStorage.removeItem(SESSION_LOGS_KEY);
  sessionStorage.removeItem(SESSION_REPORTS_KEY);
  sessionStorage.removeItem(SESSION_REPORT_TAB_KEY);
}

function appendLog(text, cls = '') {
  const line = document.createElement('div');
  if (cls) line.className = cls;
  line.textContent = text;
  logBox.appendChild(line);
  logBox.scrollTop = logBox.scrollHeight;
  persistSessionLogs();
}

function clearLog() {
  logBox.innerHTML = '';
  persistSessionLogs();
}

let langMapPromise = null;

function isLangCaptureable(code) {
  return Boolean(langMap[code]?.portalLabel);
}

function getSelectedLang() {
  return langSelect.value || '';
}

function getSelectedLangCodes() {
  const lang = getSelectedLang();
  return lang ? [lang] : [];
}

function langOptionLabel(col) {
  const cfg = langMap[col.code];
  const display = cfg?.portalLabel || col.label;
  const suffix = isLangCaptureable(col.code) ? '' : '（僅驗證）';
  return `${display} (${col.code})${suffix}`;
}

function renderLangSelect() {
  const prev = langSelect.value || localStorage.getItem(LANG_STORAGE_KEY) || '';
  langSelect.innerHTML = '';
  if (!xlsxLangs.length) {
    const opt = document.createElement('option');
    opt.value = '';
    opt.textContent = '請先上傳 xlsx';
    opt.disabled = true;
    opt.selected = true;
    langSelect.appendChild(opt);
    langSelect.disabled = true;
    updateStartBtn();
    return;
  }
  langSelect.disabled = false;
  for (const col of xlsxLangs) {
    const opt = document.createElement('option');
    opt.value = col.code;
    opt.textContent = langOptionLabel(col);
    if (!isLangCaptureable(col.code)) {
      opt.title = '未設定 langMap.portalLabel，無法擷取';
    }
    langSelect.appendChild(opt);
  }
  const codes = xlsxLangs.map(l => l.code);
  const pick = codes.includes(prev) ? prev : (codes.includes('bn') ? 'bn' : codes[0]);
  langSelect.value = pick;
  localStorage.setItem(LANG_STORAGE_KEY, pick);
  updateStartBtn();
}

async function ensureLangMap() {
  if (langMapPromise) return langMapPromise;
  langMapPromise = fetch('/api/lang-map')
    .then(res => (res.ok ? res.json() : {}))
    .then(data => { langMap = data || {}; })
    .catch(() => { langMap = {}; });
  return langMapPromise;
}

async function loadLangMap() {
  await ensureLangMap();
  renderLangSelect();
}

langSelect.addEventListener('change', () => {
  if (langSelect.value) localStorage.setItem(LANG_STORAGE_KEY, langSelect.value);
  updateStartBtn();
});

function updateStartBtn() {
  const hasFile = Boolean(xlsxFile);
  const lang = getSelectedLang();
  const hasLang = Boolean(lang);
  const canCapture = hasLang && isLangCaptureable(lang);
  startBtn.disabled = !hasFile || !canCapture;
  startBtn.title = hasFile && hasLang && !canCapture
    ? '此語系未設定 langMap.portalLabel，無法擷取（可驗證既有截圖）'
    : '';
  verifyBtn.disabled = !hasFile || !hasLang || !apiKeyInput.value.trim();
  updateManualBar();
}

async function persistXlsxSession(file) {
  try {
    if (!file || file.size > MAX_XLSX_SESSION_BYTES) {
      sessionStorage.removeItem(SESSION_XLSX_KEY);
      return;
    }
    const b64 = arrayBufferToBase64(await file.arrayBuffer());
    sessionStorage.setItem(SESSION_XLSX_KEY, JSON.stringify({
      name: file.name,
      size: file.size,
      base64: b64,
    }));
  } catch {
    sessionStorage.removeItem(SESSION_XLSX_KEY);
  }
}

async function restoreXlsxSession() {
  try {
    const raw = sessionStorage.getItem(SESSION_XLSX_KEY);
    if (!raw) return;
    const { name, base64, size } = JSON.parse(raw);
    if (!name || !base64) return;
    const binary = atob(base64);
    const buf = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) buf[i] = binary.charCodeAt(i);
    const file = new File([buf], name, {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    });
    if (size && file.size !== size) return;
    await handleFile(file, { fromSession: true });
  } catch {
    sessionStorage.removeItem(SESSION_XLSX_KEY);
  }
}

function arrayBufferToBase64(buf) {
  const bytes = new Uint8Array(buf);
  let binary = '';
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunk));
  }
  return btoa(binary);
}

/** 由勾選的工作表（S0xx）換算出對應 Slot 清單，回填到 Slot 輸入框 */
function syncSlotsFromSheets() {
  const slots = [];
  for (const s of sheets) {
    if (!selectedSheets.has(s.name)) continue;
    const slot = sheetToSlot(s.name);
    if (slot) slots.push(slot);
  }
  slotsInput.value = slots.join(',');
  persistSessionSlots();
}

/** 由 Slot 輸入框反推勾選的工作表（與 syncSlotsFromSheets 雙向連動） */
function syncSheetsFromSlots() {
  if (!sheets.length) return;
  const slots = slotsInput.value.split(',').map(s => s.trim()).filter(Boolean);
  const next = new Set();
  for (const slot of slots) {
    const sheet = slotToSheet(slot);
    if (sheet && sheets.some(s => s.name === sheet)) next.add(sheet);
  }
  selectedSheets = next;
  renderSheets();
}

function onSlotsInputChanged() {
  persistSessionSlots();
  syncSheetsFromSlots();
  updateStartBtn();
}

function renderSheets() {
  sheetList.innerHTML = '';
  for (const s of sheets) {
    const mappable = !!sheetToSlot(s.name);
    const chip = document.createElement('button');
    chip.type = 'button';
    chip.className = 'sheet-chip' + (selectedSheets.has(s.name) ? ' active' : '');
    chip.textContent = `${s.name} (${s.rowCount} 列)`;
    if (!mappable) chip.title = '此工作表名稱非 S0xx，無法對應 Slot';
    chip.addEventListener('click', () => {
      if (selectedSheets.has(s.name)) selectedSheets.delete(s.name);
      else selectedSheets.add(s.name);
      syncSlotsFromSheets();
      renderSheets();
    });
    sheetList.appendChild(chip);
  }
}

async function handleFile(file, { fromSession = false } = {}) {
  if (!file) return;
  if (!/\.xlsx?$/i.test(file.name)) {
    alert('請上傳 .xlsx 檔案');
    return;
  }
  xlsxFile = file;
  dropZone.classList.add('has-file');
  fileInfo.hidden = false;
  fileInfo.textContent = `已載入：${file.name}（${(file.size / 1024).toFixed(1)} KB）`;

  try {
    const meta = await parseXlsxMeta(file);
    sheets = meta.sheets;
    xlsxLangs = meta.langs;
    if (!xlsxLangs.length) {
      throw new Error('找不到語系欄位，欄名需含括號代碼，例如 Bangla(bn)');
    }
    await ensureLangMap();
    renderLangSelect();
    syncSheetsFromSlots();
    persistSessionSlots();
    updateStartBtn();
    await persistXlsxSession(file);
    const langNames = xlsxLangs.map(l => l.code).join(', ');
    if (fromSession) {
      appendLog(`已還原翻譯表：${file.name}（${sheets.length} 工作表、${xlsxLangs.length} 語系：${langNames}）`, 'log-ok');
    } else {
      appendLog(`已解析 ${sheets.length} 個工作表、${xlsxLangs.length} 個語系（${langNames}）`, 'log-ok');
    }
  } catch (err) {
    appendLog(`解析失敗：${err.message}`, 'log-err');
  }
}

dropZone.addEventListener('click', () => fileInput.click());
fileInput.addEventListener('change', () => handleFile(fileInput.files[0]));

dropZone.addEventListener('dragover', e => {
  e.preventDefault();
  dropZone.classList.add('dragover');
});
dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragover'));
dropZone.addEventListener('drop', e => {
  e.preventDefault();
  dropZone.classList.remove('dragover');
  handleFile(e.dataTransfer.files[0]);
});

slotsInput.addEventListener('change', onSlotsInputChanged);
slotsInput.addEventListener('blur', onSlotsInputChanged);
slotsInput.addEventListener('input', updateStartBtn);
envSelect.addEventListener('change', persistSessionSlots);

startBtn.addEventListener('click', async () => {
  if (!xlsxFile) return;

  const slots = slotsInput.value.split(',').map(s => s.trim()).filter(Boolean);
  if (!slots.length) {
    alert('請輸入至少一個 Slot');
    return;
  }
  const lang = getSelectedLang();
  if (!isLangCaptureable(lang)) {
    alert(`語系 ${lang} 無法擷取。\n請在 config.json langMap 設定 portalLabel，或改選其他語系。`);
    return;
  }
  persistSessionSlots();

  startBtn.disabled = true;
  clearLog();
  clearSessionState();
  lastReports = [];
  activeReportTab = 0;
  selectedKey = null;
  renderReports();
  exportBtn.disabled = true;
  appendLog(`啟動擷取（${lang}）…`);

  try {
    const res = await fetch('/api/capture', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        env: envSelect.value,
        lang,
        slots,
        xlsxFileName: xlsxFile.name,
      }),
    });

    if (!res.ok && res.status !== 200) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.error || `HTTP ${res.status}`);
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const lines = buf.split('\n');
      buf = lines.pop() || '';
      for (const line of lines) {
        if (!line.trim()) continue;
        try {
          const evt = JSON.parse(line);
          if (evt.type === 'log') appendLog(evt.message);
          else if (evt.type === 'done') {
            const langTag = evt.lang ? ` / ${evt.lang}` : '';
            appendLog(`✓ ${evt.slotId}${langTag} → ${evt.outDir}`, 'log-ok');
          }
          else if (evt.type === 'slot-error') {
            const langTag = evt.lang ? ` / ${evt.lang}` : '';
            const partial = evt.files?.length ? `（已存 ${evt.files.length} 張）` : '';
            appendLog(`✗ ${evt.slotId}${langTag}：${evt.message}${partial}`, 'log-err');
          }
          else if (evt.type === 'error') appendLog(`✗ ${evt.message}`, 'log-err');
          else if (evt.type === 'complete') {
            const failed = evt.failedCount ?? 0;
            const ok = evt.okCount ?? (evt.results?.length ?? 0) - failed;
            if (failed > 0) {
              appendLog(`全部完成：成功 ${ok}、失敗 ${failed}`, failed === evt.results?.length ? 'log-err' : 'log-ok');
            } else {
              appendLog('全部完成', 'log-ok');
            }
          }
        } catch { /* ignore */ }
      }
    }
  } catch (err) {
    appendLog(`失敗：${err.message}`, 'log-err');
  } finally {
    updateStartBtn();
  }
});

// ===== 階段 C：孟加拉文驗證 =====

function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

function captureImageUrl(env, lang, slotId, file) {
  if (!file || !env || !lang || !slotId) return '';
  return `/api/captures/${encodeURIComponent(env)}/${encodeURIComponent(lang)}/${encodeURIComponent(slotId)}/${encodeURIComponent(file)}`;
}

function filteredRows(rep) {
  const rows = rep.results || [];
  if (!statusFilter) return rows;
  return rows.filter(r => r.status === statusFilter);
}

function statusPill(status, count, cls) {
  const active = statusFilter === status ? ' active' : '';
  return `<button type="button" class="pill pill-btn ${cls}${active}" data-status="${status}">${status} ${count}</button>`;
}

function rowDisplayFile(row) {
  return row.displayFile || row.sourceFile || '';
}

function rowPreviewUrl(rep, row) {
  const manual = getManualImageUrl(rep, row);
  if (manual) return manual;
  const file = rowDisplayFile(row);
  if (!file) return '';
  const env = rep.env || envSelect.value;
  const lang = rep.lang || getSelectedLangCodes()[0] || 'bn';
  return captureImageUrl(env, lang, rep.slotId, file);
}

function renderActionsCell(rep, r) {
  if (r.manualPaste) return '';
  if (r.status !== 'FAIL' && r.status !== 'REVIEW') return '';
  const source = r.sourceFile || rowDisplayFile(r);
  if (!source || !/\.png$/i.test(source)) return '';
  const busy = reocrBusy ? ' disabled' : '';
  return `<button type="button" class="btn-reocr" data-source="${escapeHtml(source)}" data-key="${escapeHtml(r.key)}"${busy}>重 OCR</button>`;
}

async function runReOcr(rep, sourceFile, key) {
  if (!xlsxFile || reocrBusy) return;
  const apiKey = apiKeyInput.value.trim();
  if (!apiKey) {
    alert(`請先輸入 ${getApiKeyLabel(getLlmProvider())}`);
    return;
  }

  reocrBusy = true;
  renderReports();
  appendLog(`重 OCR ${rep.slotId} / ${sourceFile}（${key}）…`);

  try {
    const xlsxBase64 = arrayBufferToBase64(await xlsxFile.arrayBuffer());
    const res = await fetch('/api/verify-reocr', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        env: rep.env || envSelect.value,
        lang: rep.lang || getSelectedLangCodes()[0] || 'bn',
        slotId: rep.slotId,
        sheetName: rep.sheet,
        sourceFile,
        xlsxBase64,
        provider: getLlmProvider(),
        apiKey,
        modelId: modelSelect.value,
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);

    rep.results = data.results || rep.results;
    rep.summary = data.summary || recomputeSummary(rep.results);
    rep.cacheCoverage = data.cacheCoverage;
    rep.cacheTotal = data.cacheTotal;
    rep.cacheHits = data.cacheHits;
    rep.ocrApiCalls = data.ocrApiCalls;

    const tu = data.tokenUsage;
    const tokenPart = tu?.totalTokens
      ? ` · token ${tu.promptTokens} in / ${tu.completionTokens} out`
      : '';
    appendLog(
      `重 OCR 完成 ${sourceFile} → API ${data.ocrApiCalls ?? 1} 次 · PASS ${rep.summary.PASS} / FAIL ${rep.summary.FAIL}${tokenPart}`,
      'log-ok',
    );
    persistSessionReports();
    renderReports();
  } catch (err) {
    appendLog(`重 OCR 失敗：${err.message}`, 'log-err');
    renderReports();
  } finally {
    reocrBusy = false;
    updateManualBar();
    renderReports();
  }
}

function renderSourceCell(rep, r) {
  const manualUrl = getManualImageUrl(rep, r);
  const env = rep.env || envSelect.value;
  const lang = rep.lang || getSelectedLangCodes()[0] || 'bn';

  if (manualUrl) {
    const warn = r.issueNote
      ? `<br><span class="thumb-warn">${escapeHtml(r.issueNote)}</span>`
      : '';
    return `<div class="source-cell">
    <div class="thumb-wrap" data-slot="${escapeHtml(rep.slotId)}" data-lang="${escapeHtml(lang)}" data-key="${escapeHtml(r.key)}" title="點擊放大（← → 切換）">
      <img src="${manualUrl}" alt="手動貼圖" loading="lazy">
    </div>
    <div class="thumb-meta">（手動貼圖）${warn}</div>
  </div>`;
  }

  const previewFile = rowDisplayFile(r);
  if (!previewFile) return '—';
  const url = captureImageUrl(env, lang, rep.slotId, previewFile);
  const matchNote = r.sourceFile && r.displayFile && r.sourceFile !== r.displayFile
    ? `<br><span class="thumb-warn">命中 ${escapeHtml(r.sourceFile)}</span>`
    : '';
  const warn = r.issueNote
    ? `<br><span class="thumb-warn">${escapeHtml(r.issueNote)}</span>`
    : (r.isLoadingKey && r.status === 'FAIL'
      ? '<br><span class="st-loading-fail">Loading 未命中</span>'
      : '');
  return `<div class="source-cell">
    <div class="thumb-wrap" data-slot="${escapeHtml(rep.slotId)}" data-lang="${escapeHtml(lang)}" data-key="${escapeHtml(r.key)}" title="點擊放大（← → 切換）">
      <img src="${url}" alt="${escapeHtml(previewFile)}" loading="lazy">
    </div>
    <div class="thumb-meta">${escapeHtml(previewFile)}${matchNote}${warn}</div>
  </div>`;
}

const lightbox = document.getElementById('lightbox');
const lightboxClose = document.getElementById('lightboxClose');
const lightboxPrev = document.getElementById('lightboxPrev');
const lightboxNext = document.getElementById('lightboxNext');
const lightboxCounter = document.getElementById('lightboxCounter');
const lightboxImgWrap = document.getElementById('lightboxImgWrap');
const lightboxSide = document.getElementById('lightboxSide');

function buildPreviewItems(rep) {
  return filteredRows(rep)
    .filter(r => rowPreviewUrl(rep, r))
    .map(row => ({ rep, row }));
}

function closeLightbox() {
  lightbox.classList.remove('open');
  lightbox.hidden = true;
  lightboxImgWrap.innerHTML = '';
  lightboxSide.innerHTML = '';
  previewIndex = -1;
}

function renderLightboxContent() {
  if (previewIndex < 0 || previewIndex >= previewItems.length) return;
  const { rep, row } = previewItems[previewIndex];
  const url = rowPreviewUrl(rep, row);
  const previewFile = row.manualPaste ? '（手動貼圖）' : rowDisplayFile(row);
  const matchLine = !row.manualPaste && row.sourceFile && row.displayFile && row.sourceFile !== row.displayFile
    ? `<p style="margin:-6px 0 10px;color:var(--muted);font-size:13px">文案命中：${escapeHtml(row.sourceFile)}</p>`
    : '';
  lightboxImgWrap.innerHTML = `<img src="${url}" alt="${escapeHtml(previewFile)}">`;
  const hl = (row.highlightLines || []).map(l =>
    `<div class="hl-line matched">${escapeHtml(l)}</div>`
  ).join('');
  lightboxSide.innerHTML = `
    <h4>${escapeHtml(row.key)} · ${escapeHtml(previewFile)}</h4>
    ${matchLine}
    ${row.issueNote ? `<p style="margin-bottom:10px;color:#ffd43b">⚠ ${escapeHtml(row.issueNote)}</p>` : ''}
    <div style="margin-bottom:12px"><strong>預期（${escapeHtml(rep.lang || getSelectedLang())}）：</strong><div class="bn" style="margin-top:4px">${escapeHtml(row.expected)}</div></div>
    <div style="margin-bottom:6px"><strong>OCR 片段：</strong></div>
    ${hl || `<div class="hl-line other">${escapeHtml(row.snippet || '（無）')}</div>`}
    <div style="margin-top:12px;color:var(--muted)">相似度 ${(row.similarity * 100).toFixed(0)}% · ${row.status}</div>`;
  lightboxCounter.textContent = `${previewIndex + 1} / ${previewItems.length}`;
  lightboxPrev.disabled = previewIndex <= 0;
  lightboxNext.disabled = previewIndex >= previewItems.length - 1;
}

function openPreview(rep, row) {
  previewItems = buildPreviewItems(rep);
  previewIndex = previewItems.findIndex(p => p.row.key === row.key);
  if (previewIndex < 0) previewIndex = 0;
  lightbox.hidden = false;
  lightbox.classList.add('open');
  renderLightboxContent();
}

function stepPreview(delta) {
  const next = previewIndex + delta;
  if (next < 0 || next >= previewItems.length) return;
  previewIndex = next;
  renderLightboxContent();
}

lightboxClose.addEventListener('click', closeLightbox);
lightbox.addEventListener('click', e => { if (e.target === lightbox) closeLightbox(); });
lightboxPrev.addEventListener('click', () => stepPreview(-1));
lightboxNext.addEventListener('click', () => stepPreview(1));
document.addEventListener('keydown', e => {
  if (!lightbox.classList.contains('open')) return;
  if (e.key === 'Escape') closeLightbox();
  if (e.key === 'ArrowLeft') { e.preventDefault(); stepPreview(-1); }
  if (e.key === 'ArrowRight') { e.preventDefault(); stepPreview(1); }
});
resultArea.addEventListener('click', e => {
  const reocrBtn = e.target.closest('.btn-reocr');
  if (reocrBtn) {
    e.stopPropagation();
    const rep = lastReports[activeReportTab];
    if (!rep || reocrBusy) return;
    runReOcr(rep, reocrBtn.dataset.source, reocrBtn.dataset.key);
    return;
  }
  const wrap = e.target.closest('.thumb-wrap');
  if (wrap) {
    const rep = lastReports.find(r =>
      r.slotId === wrap.dataset.slot && (r.lang || '') === (wrap.dataset.lang || ''),
    );
    const row = rep?.results?.find(r => r.key === wrap.dataset.key);
    if (rep && row) openPreview(rep, row);
    return;
  }
  const tr = e.target.closest('tr[data-key]');
  if (tr) {
    selectedKey = tr.dataset.key;
    updateManualBar();
    resultArea.querySelectorAll('tr.row-selected').forEach(r => r.classList.remove('row-selected'));
    tr.classList.add('row-selected');
  }
});

function renderSlotTable(rep) {
  const langLabel = rep.lang || getSelectedLang() || '—';
  const s = rep.summary || { PASS: 0, REVIEW: 0, FAIL: 0 };
  const rows = filteredRows(rep);
  const loadingFails = (rep.results || []).filter(r => r.isLoadingKey && r.status === 'FAIL').length;
  const showLoadingHint = loadingFails > 0 && (!statusFilter || statusFilter === 'FAIL');
  const cacheReady = rep.cacheCoverage?.ready ?? rep.cacheHits ?? 0;
  const cacheTotal = rep.cacheTotal ?? rep.ocrCount ?? 0;
  const cacheLine = cacheTotal > 0
    ? `<p class="cache-coverage">OCR 快取覆蓋 ${cacheReady}/${cacheTotal} 張${rep.ocrApiCalls != null ? ` · 本次 API ${rep.ocrApiCalls} 次` : ''}</p>`
    : '';
  const head = `<div class="summary-pills">
      ${statusPill('PASS', s.PASS, 'pass')}
      ${statusPill('REVIEW', s.REVIEW, 'review')}
      ${statusPill('FAIL', s.FAIL, 'fail')}
      ${statusFilter ? `<button type="button" class="pill pill-btn" data-status-clear>顯示全部</button>` : ''}
      ${showLoadingHint ? `<span class="pill fail">Loading 未命中 ${loadingFails}</span>` : ''}
    </div>
    ${showLoadingHint ? '<p class="hint" style="margin:8px 0">Loading FAIL：對應輪播截圖未找到該 key 文案。預覽圖依 key 編號顯示 Loading_N.png。</p>' : ''}
    ${cacheLine}`;

  const body = rows.map(r => `
      <tr data-key="${escapeHtml(r.key)}" class="${r.key === selectedKey ? 'row-selected' : ''}">
        <td>${escapeHtml(r.key)}</td>
        <td class="bn">${escapeHtml(r.expected)}</td>
        <td>${(r.similarity * 100).toFixed(0)}%</td>
        <td class="st-${r.status}">${r.status}</td>
        <td>${renderSourceCell(rep, r)}</td>
        <td class="bn">${escapeHtml(r.snippet || '')}</td>
        <td>${renderActionsCell(rep, r)}</td>
      </tr>`).join('');

  return `${head}
    <div class="table-wrap"><table class="result-table">
      <thead><tr><th>Key</th><th>預期（${escapeHtml(langLabel)}）</th><th>相似度</th><th>狀態</th><th>來源圖</th><th>OCR 片段</th><th>操作</th></tr></thead>
      <tbody>${body || '<tr><td colspan="7">（無符合篩選的列）</td></tr>'}</tbody>
    </table></div>`;
}

function captureResultScroll() {
  const tableWrap = resultArea.querySelector('.table-wrap');
  if (!tableWrap) return null;
  return { tableScrollTop: tableWrap.scrollTop, pageY: window.scrollY };
}

function restoreResultScroll(saved) {
  if (!saved) return;
  const apply = () => {
    window.scrollTo(0, saved.pageY);
    const tableWrap = resultArea.querySelector('.table-wrap');
    if (tableWrap) tableWrap.scrollTop = saved.tableScrollTop;
  };
  apply();
  requestAnimationFrame(apply);
}

function renderReports() {
  if (!lastReports.length) {
    resultCard.hidden = true;
    manualBar.hidden = true;
    return;
  }
  const savedScroll = captureResultScroll();
  if (activeReportTab >= lastReports.length) activeReportTab = 0;
  resultCard.hidden = false;

  resultTabsBar.innerHTML = lastReports.map((rep, i) => {
    const s = rep.summary || {};
    const fail = (s.FAIL || 0) + (s.REVIEW || 0);
    return `<button type="button" class="result-tab${i === activeReportTab ? ' active' : ''}" data-idx="${i}">
      ${escapeHtml(rep.slotId)} / ${escapeHtml(rep.lang || '?')}（${escapeHtml(rep.sheet)}）${fail ? ` · ${fail} 待查` : ''}
    </button>`;
  }).join('');

  resultTabsBar.querySelectorAll('.result-tab').forEach(btn => {
    btn.addEventListener('click', () => {
      activeReportTab = Number(btn.dataset.idx);
      const rep = lastReports[activeReportTab];
      if (selectedKey && !rep?.results?.some(r => r.key === selectedKey)) {
        selectedKey = null;
      }
      persistSessionReports();
      renderReports();
    });
  });

  const rep = lastReports[activeReportTab];
  if (selectedKey && !rep?.results?.some(r => r.key === selectedKey)) {
    selectedKey = null;
  }
  resultArea.innerHTML = renderSlotTable(rep);
  updateManualBar();

  resultArea.querySelectorAll('.pill-btn[data-status]').forEach(btn => {
    btn.addEventListener('click', () => {
      const st = btn.dataset.status;
      statusFilter = statusFilter === st ? null : st;
      renderReports();
    });
  });
  resultArea.querySelector('[data-status-clear]')?.addEventListener('click', () => {
    statusFilter = null;
    renderReports();
  });
  restoreResultScroll(savedScroll);
}

exportBtn.addEventListener('click', async () => {
  if (!lastReports.length) return;
  const wb = new window.ExcelJS.Workbook();
  const ws = wb.addWorksheet('驗證結果');
  ws.columns = [
    { header: 'Slot', key: 'slot', width: 12 },
    { header: '語系', key: 'lang', width: 8 },
    { header: '工作表', key: 'sheet', width: 10 },
    { header: 'Key', key: 'key', width: 28 },
    { header: '預期文案', key: 'expected', width: 48 },
    { header: '相似度', key: 'similarity', width: 10 },
    { header: '狀態', key: 'status', width: 10 },
    { header: '預覽圖', key: 'displayFile', width: 20 },
    { header: '命中圖', key: 'sourceFile', width: 20 },
    { header: '備註', key: 'issueNote', width: 28 },
    { header: 'OCR 片段', key: 'snippet', width: 48 },
  ];
  for (const rep of lastReports) {
    for (const r of rep.results || []) {
      ws.addRow({
        slot: rep.slotId,
        lang: rep.lang || '',
        sheet: rep.sheet,
        key: r.key,
        expected: r.expected,
        similarity: `${(r.similarity * 100).toFixed(0)}%`,
        status: r.status,
        displayFile: r.manualPaste ? '（手動貼圖）' : (r.displayFile || r.sourceFile || ''),
        sourceFile: r.manualPaste ? '（手動貼圖）' : (r.sourceFile || ''),
        issueNote: r.issueNote || '',
        snippet: r.snippet,
      });
    }
  }
  const out = await wb.xlsx.writeBuffer();
  const blob = new Blob([out], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
  const langs = [...new Set(lastReports.map(r => r.lang).filter(Boolean))];
  const langTag = langs.length === 1 ? langs[0] : (langs.length ? langs.join('-') : getSelectedLang() || 'lang');
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `l10n-verify_${envSelect.value}_${langTag}_${Date.now()}.xlsx`;
  a.click();
  URL.revokeObjectURL(a.href);
});

verifyBtn.addEventListener('click', async () => {
  const apiKey = apiKeyInput.value.trim();
  if (!xlsxFile || !apiKey) return;
  const slots = slotsInput.value.split(',').map(s => s.trim()).filter(Boolean);
  if (!slots.length) {
    alert('請輸入至少一個 Slot');
    return;
  }

  const lang = getSelectedLang();
  if (!lang) {
    alert('請選擇語系');
    return;
  }
  persistSessionSlots();

  verifyBtn.disabled = true;
  exportBtn.disabled = true;
  startBtn.disabled = true;
  lastReports = [];
  activeReportTab = 0;
  selectedKey = null;
  statusFilter = null;
  clearLog();
  clearSessionState();
  renderReports();
  appendLog(`啟動驗證（${lang}）…`);

  try {
    const xlsxBase64 = arrayBufferToBase64(await xlsxFile.arrayBuffer());
    const res = await fetch('/api/verify', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        env: envSelect.value,
        lang,
        slots,
        xlsxBase64,
        provider: getLlmProvider(),
        apiKey,
        modelId: modelSelect.value,
        forceOcr: forceOcrToggle.checked,
      }),
    });

    if (!res.ok && res.status !== 200) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.error || `HTTP ${res.status}`);
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const lines = buf.split('\n');
      buf = lines.pop() || '';
      for (const line of lines) {
        if (!line.trim()) continue;
        try {
          const evt = JSON.parse(line);
          if (evt.type === 'log') appendLog(evt.message);
          else if (evt.type === 'slot-done') {
            const { type, ...rep } = evt;
            lastReports.push(rep);
            persistSessionReports();
            renderReports();
            exportBtn.disabled = false;
          } else if (evt.type === 'error') appendLog(`✗ ${evt.message}`, 'log-err');
          else if (evt.type === 'complete') {
            if (evt.usageSummary?.slots) {
              const u = evt.usageSummary;
              const parts = [`${u.slots} 款`, `OCR API ${u.ocrApiCalls} 次`];
              if (u.totalTokens > 0) parts.push(`token ${u.promptTokens} in / ${u.completionTokens} out`);
              if (u.apiCostReported) parts.push(`$${u.costUsd.toFixed(4)}`);
              appendLog(`驗證完成 · ${parts.join(' · ')}`, 'log-ok');
            } else {
              appendLog('驗證完成', 'log-ok');
            }
            persistSessionReports();
          }
        } catch { /* ignore */ }
      }
    }
  } catch (err) {
    appendLog(`驗證失敗：${err.message}`, 'log-err');
  } finally {
    updateStartBtn();
  }
});

reverifyPasteBtn.addEventListener('click', async () => {
  const rep = lastReports[activeReportTab];
  if (!rep || !selectedKey) return;
  const blob = manualImageBlobs.get(manualRowId(rep, selectedKey));
  if (!blob) return;
  await runPasteVerify(rep, selectedKey, blob);
});

document.addEventListener('paste', e => {
  if (!lastReports.length || lightbox.classList.contains('open') || manualPasteBusy) return;
  if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement || e.target instanceof HTMLSelectElement) {
    return;
  }
  const rep = lastReports[activeReportTab];
  if (!rep || !selectedKey) return;

  const items = e.clipboardData?.items;
  if (!items) return;

  for (const item of items) {
    if (!item.type.startsWith('image/')) continue;
    const blob = item.getAsFile();
    if (!blob) continue;
    e.preventDefault();
    const pastedKey = selectedKey;
    if (!attachManualImage(rep, pastedKey, blob)) return;
    renderReports();
    runPasteVerify(rep, pastedKey, blob);
    break;
  }
});

loadLangMap().then(async () => {
  restoreSessionSlots();
  restoreSessionLogs();
  restoreSessionReports();
  await restoreXlsxSession();
});
