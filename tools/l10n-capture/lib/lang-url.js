/** 從遊戲 URL 解析語系（Comboburst 使用 ?l=bn / ?l=en-US） */
export function parseGameLocale(url, paramNames = ['l', 'lang', 'locale']) {
  try {
    const u = new URL(url);
    for (const p of paramNames) {
      const v = u.searchParams.get(p);
      if (v) return v.trim();
    }
  } catch {
    /* ignore */
  }
  return '';
}

/**
 * 比對 URL 語系與預期 urlCode（en ↔ en-US、zh-Hant ↔ zh-Hant-*）。
 * @param {string} expected config.langMap.*.urlCode
 * @param {string} actual URL 上的 l=
 * @param {string[]} [aliases] 額外可接受值（如 en-US）
 */
export function localeMatches(expected, actual, aliases = []) {
  if (!expected) return Boolean(actual);
  if (!actual) return false;
  const exp = expected.trim();
  const act = actual.trim();
  if (act === exp) return true;
  if (act.startsWith(`${exp}-`)) return true;
  if (exp.startsWith(`${act}-`)) return true;
  return aliases.some(a => {
    const alias = String(a).trim();
    return act === alias || act.startsWith(`${alias}-`);
  });
}
