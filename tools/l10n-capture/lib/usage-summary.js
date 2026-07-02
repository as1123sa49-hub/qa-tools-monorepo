/** 彙總多個 verifySlot 報告的 OCR token / API 次數 */
export function sumVerifyReports(reports) {
  const acc = {
    slots: 0,
    ocrApiCalls: 0,
    cacheHits: 0,
    scrollDeduped: 0,
    promptTokens: 0,
    completionTokens: 0,
    totalTokens: 0,
    imageTokens: 0,
    costUsd: 0,
    apiCostReported: false,
  };
  if (!Array.isArray(reports)) return acc;
  for (const r of reports) {
    if (!r || r.aborted) continue;
    acc.slots++;
    acc.ocrApiCalls += r.ocrApiCalls ?? 0;
    acc.cacheHits += r.cacheHits ?? 0;
    acc.scrollDeduped += r.scrollDeduped ?? 0;
    const tu = r.tokenUsage;
    if (!tu) continue;
    acc.promptTokens += tu.promptTokens ?? 0;
    acc.completionTokens += tu.completionTokens ?? 0;
    acc.totalTokens += tu.totalTokens ?? 0;
    acc.imageTokens += tu.imageTokens ?? 0;
    if (tu.apiCostReported && tu.costUsd != null) {
      acc.costUsd += tu.costUsd;
      acc.apiCostReported = true;
    }
  }
  return acc;
}

export function formatUsageSummary(summary) {
  if (!summary?.slots) return '';
  const parts = [
    `${summary.slots} 款`,
    `OCR API ${summary.ocrApiCalls} 次`,
  ];
  if (summary.totalTokens > 0) {
    parts.push(`token ${summary.promptTokens} in / ${summary.completionTokens} out`);
  }
  if (summary.apiCostReported) {
    parts.push(`$${summary.costUsd.toFixed(4)}`);
  }
  if (summary.cacheHits > 0) parts.push(`快取 ${summary.cacheHits}`);
  if (summary.scrollDeduped > 0) parts.push(`去重 ${summary.scrollDeduped}`);
  return parts.join(' · ');
}
