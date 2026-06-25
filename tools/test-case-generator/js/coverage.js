/**
 * PRD / 模組覆蓋率統計（不需 AI）
 */
import { normalizeMainModule, stripFeatureMarkers } from './case-utils.js';

function docStem(name) {
  return (name || '').toLowerCase().replace(/\.(pdf|docx|xlsx|csv)$/i, '');
}

function docKeywords(docName) {
  const nameLower = (docName || '').toLowerCase();
  const stem = docStem(docName);
  const keywords = stem
    .split(/[\s_\-&【】\[\]()]+/)
    .map(s => s.trim())
    .filter(s => s.length >= 3 && !/^\d{6,}$/.test(s));
  return { nameLower, stem, keywords };
}

/** 案例規格來源是否對應到某份 PRD 檔名 */
export function caseMatchesDoc(rawSrc, docName) {
  const src = (rawSrc || '').toLowerCase();
  if (!src || /^(無|—|-)$/i.test(src.trim())) return false;
  const { nameLower, stem, keywords } = docKeywords(docName);
  if (src.includes(nameLower)) return true;
  if (stem.length >= 3 && src.includes(stem)) return true;
  return keywords.some(kw => kw.length >= 4 && src.includes(kw));
}

/** 依功能規格書檔名統計案例數 */
export function buildPrdCoverageReport(docNames, cases) {
  const names = [...new Set((docNames || []).map(n => n.trim()).filter(Boolean))];
  const items = names.map(name => {
    const matched = (cases || []).filter(c => caseMatchesDoc(c['規格來源'], name));
    return { name, count: matched.length, covered: matched.length > 0 };
  });

  const unmatchedCases = (cases || []).filter(c => {
    const src = (c['規格來源'] || '').trim();
    if (!src || /^(無|—|-)$/i.test(src)) return true;
    if (!names.length) return false;
    return !names.some(name => caseMatchesDoc(src, name));
  });

  return {
    items,
    totalCases: (cases || []).length,
    unmatchedToPrd: unmatchedCases.length,
    prdWithCases: items.filter(i => i.covered).length,
    prdTotal: items.length,
  };
}

export function formatPrdCoverageWarning(report) {
  if (!report?.items?.length) return null;
  const missing = report.items.filter(i => !i.covered).map(i => i.name);
  if (!missing.length) return null;
  return `⚠ 規格來源未涵蓋 ${missing.length} 份功能規格書：${missing.join('、')}。請確認每份規格書皆有產出案例，或改分批後用附加模式合併。`;
}

/** 案例規格來源是否對應到 XLSX 某工作表 */
export function caseMatchesSheet(rawSrc, sheetName, fileName = '') {
  const src = (rawSrc || '').trim();
  if (!src || /^(無|—|-)$/i.test(src)) return false;
  const sheet = (sheetName || '').trim();
  if (!sheet) return false;
  if (src.includes(` / ${sheet} /`) || src.includes(`/${sheet}/`)) return true;
  if (fileName && caseMatchesDoc(src, fileName)) {
    return src.toLowerCase().includes(sheet.toLowerCase());
  }
  return src.toLowerCase().includes(sheet.toLowerCase());
}

/** 依 XLSX 工作表名稱統計案例數 */
export function buildXlsxSheetCoverageReport(fileName, sheetNames, cases) {
  const sheets = [...new Set((sheetNames || []).map(s => s.trim()).filter(Boolean))];
  const items = sheets.map(name => {
    const matched = (cases || []).filter(c => caseMatchesSheet(c['規格來源'], name, fileName));
    return { name, count: matched.length, covered: matched.length > 0 };
  });
  return {
    fileName: (fileName || '').trim(),
    items,
    sheetWithCases: items.filter(i => i.covered).length,
    sheetTotal: items.length,
  };
}

export function formatXlsxSheetCoverageWarning(report) {
  if (!report?.items?.length) return null;
  const missing = report.items.filter(i => !i.covered).map(i => i.name);
  if (!missing.length) return null;
  const prefix = report.fileName ? `${report.fileName}：` : '';
  return `⚠ ${prefix}${missing.length} 個工作表未產出案例：${missing.join('、')}。請重試失敗批次或檢查該分頁內容。`;
}

/** 主模組 / L2 功能群案例分布（前 N 名） */
export function buildModuleCoverageSummary(cases, limit = 14) {
  const map = new Map();
  for (const c of cases || []) {
    const main = normalizeMainModule(c['主模組'] || '') || '未分類';
    const feat = stripFeatureMarkers(c['功能頁面/元件'] || '') || '未分類';
    const l2 = feat.includes(' - ') ? feat.split(' - ')[0].trim() : feat;
    const key = `${main} / ${l2}`;
    map.set(key, (map.get(key) || 0) + 1);
  }
  return [...map.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, limit)
    .map(([key, count]) => ({ key, count }));
}

function featureGroupKey(c) {
  const main = normalizeMainModule(c['主模組'] || '') || '';
  const feat = stripFeatureMarkers(c['功能頁面/元件'] || '') || '';
  return `${main}::${feat}`;
}

/** 與基準案例集比對（主模組 + 功能頁面/元件） */
export function compareCaseSetsByFeature(baselineCases, currentCases) {
  const baseGroups = new Map();
  for (const c of baselineCases || []) {
    const k = featureGroupKey(c);
    if (!k.replace(/::/g, '')) continue;
    baseGroups.set(k, (baseGroups.get(k) || 0) + 1);
  }
  const curGroups = new Map();
  for (const c of currentCases || []) {
    const k = featureGroupKey(c);
    if (!k.replace(/::/g, '')) continue;
    curGroups.set(k, (curGroups.get(k) || 0) + 1);
  }

  const gaps = [];
  for (const [key, baseline] of baseGroups) {
    const current = curGroups.get(key) || 0;
    if (current < baseline) {
      gaps.push({ key, baseline, current, delta: current - baseline });
    }
  }
  gaps.sort((a, b) => a.delta - b.delta);

  return {
    baselineTotal: (baselineCases || []).length,
    currentTotal: (currentCases || []).length,
    deltaTotal: (currentCases || []).length - (baselineCases || []).length,
    gaps,
  };
}
