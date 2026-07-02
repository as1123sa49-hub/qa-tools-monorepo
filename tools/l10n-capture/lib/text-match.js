/** 文字正規化 + 相似度 + 視窗式最佳比對（供覆蓋式驗證使用） */

const FULLWIDTH_ASCII_START = 0xff01;
const FULLWIDTH_ASCII_END = 0xff5e;
const FULLWIDTH_OFFSET = 0xfee0;

/** 短標題類 key：只接受單行且長度接近的命中，避免內文子串誤判 */
const SHORT_TEXT_MAX = 40;
const SHORT_LINE_LEN_FACTOR = 1.25;
const WINDOW_LEN_FACTOR = 1.35;

const PUNCT_MAP = new Map([
  ['，', ','], ['。', '.'], ['、', ','], ['；', ';'], ['：', ':'],
  ['！', '!'], ['？', '?'], ['（', '('], ['）', ')'], ['「', '"'],
  ['」', '"'], ['『', '"'], ['』', '"'], ['【', '['], ['】', ']'],
  ['《', '<'], ['》', '>'], ['—', '-'], ['–', '-'], ['…', '...'],
  ['‧', '.'], ['·', '.'], ['￥', '¥'], ['％', '%'],
]);

function toHalfWidth(text) {
  let out = '';
  for (const ch of text) {
    const code = ch.charCodeAt(0);
    if (code >= FULLWIDTH_ASCII_START && code <= FULLWIDTH_ASCII_END) {
      out += String.fromCharCode(code - FULLWIDTH_OFFSET);
    } else if (code === 0x3000) {
      out += ' ';
    } else {
      out += ch;
    }
  }
  return out;
}

function unifyPunctuation(text) {
  let out = '';
  for (const ch of text) out += PUNCT_MAP.get(ch) ?? ch;
  return out;
}

/** 孟加拉數字 ০–৯ → ASCII 0–9，避免 OCR 與 xlsx 數字形式不一致 */
function bengaliDigitsToAscii(text) {
  return text.replace(/[\u09E6-\u09EF]/g, ch => String(ch.charCodeAt(0) - 0x09E6));
}

/** @param {string} text */
export function normalizeText(text) {
  if (!text) return '';
  let t = String(text).normalize('NFC');
  t = toHalfWidth(t);
  t = unifyPunctuation(t);
  t = bengaliDigitsToAscii(t);
  t = t.replace(/[\u200b\u200c\u200d\ufeff]/g, '');
  t = t.replace(/\s+/g, ' ').trim();
  return t;
}

function lcsLength(a, b) {
  const m = a.length;
  const n = b.length;
  if (!m || !n) return 0;
  const prev = new Uint32Array(n + 1);
  const curr = new Uint32Array(n + 1);
  for (let i = 1; i <= m; i++) {
    for (let j = 1; j <= n; j++) {
      if (a[i - 1] === b[j - 1]) curr[j] = prev[j - 1] + 1;
      else curr[j] = Math.max(prev[j], curr[j - 1]);
    }
    prev.set(curr);
    curr.fill(0);
  }
  return prev[n];
}

/** @param {string} a @param {string} b */
export function similarityRatio(a, b) {
  if (!a && !b) return 1;
  if (!a || !b) return 0;
  const lcs = lcsLength(a, b);
  return (2 * lcs) / (a.length + b.length);
}

/** 視窗越長於預期，分數越低（避免標題被子串帶過） */
function scoreWindow(exp, winNorm) {
  const sim = similarityRatio(exp, winNorm);
  const lenRatio = exp.length / Math.max(winNorm.length, 1);
  const lengthFactor = lenRatio < 0.75 ? lenRatio / 0.75 : 1;
  return sim * lengthFactor;
}

function makeResult(lines, lineStart, lineEnd, similarity, expected, matchType, matchNote = '') {
  const highlightLines = lineStart >= 0 ? lines.slice(lineStart, lineEnd + 1) : [];
  const snippet = highlightLines.join(' ');
  const singleLine = lineStart >= 0 && lineStart === lineEnd;
  const expNorm = normalizeText(expected);
  const snipNorm = normalizeText(snippet);
  const lenOk = !expNorm || snipNorm.length <= expNorm.length * SHORT_LINE_LEN_FACTOR;
  return {
    similarity,
    snippet,
    lineStart,
    lineEnd,
    totalLines: lines.length,
    highlightLines,
    matchType,
    matchNote,
    bandReliable: singleLine && similarity >= 0.85 && lenOk,
  };
}

/** 所有 Loading 輪播截圖（Loading_1.png …） */
export function loadingCaptureFiles(allFiles) {
  return allFiles
    .filter(f => /^loading_\d+\.png$/i.test(f))
    .sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
}

/** Buy 系 key（Buy_Bet、BuyBonus_1 …，前綴 /^Buy/i） */
export function isBuyKey(key) {
  return /^Buy/i.test(String(key || ''));
}

/** Buy Bonus 彈窗截圖（通常僅一張） */
export function buyCaptureFiles(allFiles) {
  return allFiles
    .filter(f => /^buy_/i.test(f))
    .sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
}

/** Info 捲動截圖（info_scroll_01.png …） */
export function infoCaptureFiles(allFiles) {
  return allFiles
    .filter(f => /^info_scroll_/i.test(f))
    .sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
}

/**
 * 依 key 名稱決定要在哪些截圖中搜尋。
 * Loading_* → Loading_N.png
 * Buy 系（/^Buy/i）→ buy_*.png
 * 其餘（Info_*、Title_* 等）→ info_scroll_*.png
 */
export function filesForKey(key, allFiles) {
  const loadingMatch = /^Loading_(\d+)$/i.exec(key);
  if (loadingMatch) {
    const n = loadingMatch[1];
    const own = loadingCaptureFiles(allFiles).find(
      f => f.match(/^Loading_(\d+)\.png$/i)?.[1] === n,
    );
    if (own) return [own];
    return loadingCaptureFiles(allFiles);
  }
  if (isBuyKey(key)) {
    return buyCaptureFiles(allFiles);
  }
  return infoCaptureFiles(allFiles);
}

/**
 * 在多行 OCR 文字中尋找與 expected 最相似的片段。
 * 短標題優先單行匹配；子串嵌入長內文會被長度懲罰降分。
 */
export function findBestMatch(expected, lines) {
  const exp = normalizeText(expected);
  const totalLines = lines.length;
  const empty = {
    similarity: 0,
    snippet: '',
    lineStart: -1,
    lineEnd: -1,
    totalLines,
    highlightLines: [],
    matchType: 'none',
    matchNote: '',
    bandReliable: false,
  };
  if (!exp) {
    return { ...empty, similarity: 1, lineStart: 0, lineEnd: -1 };
  }

  const isShort = exp.length <= SHORT_TEXT_MAX;
  let best = { ...empty };

  const consider = (lineStart, lineEnd, similarity, matchType, matchNote = '') => {
    if (similarity <= best.similarity) return;
    best = makeResult(lines, lineStart, lineEnd, similarity, expected, matchType, matchNote);
  };

  // 階段 1：單行匹配（標題類最可靠）
  for (let i = 0; i < lines.length; i++) {
    const lineNorm = normalizeText(lines[i]);
    if (!lineNorm) continue;
    if (lineNorm === exp) {
      return makeResult(lines, i, i, 1, expected, 'line-exact');
    }
    const sim = similarityRatio(exp, lineNorm);
    if (isShort) {
      if (sim >= 0.95 && lineNorm.length <= exp.length * SHORT_LINE_LEN_FACTOR) {
        consider(i, i, sim, 'line-fuzzy');
      }
    } else if (sim >= 0.95) {
      consider(i, i, sim, 'line-fuzzy');
    }
  }

  // 短標題已有夠好的單行命中就不再看跨行視窗
  if (isShort && best.similarity >= 0.95) return best;

  // 階段 2：跨行滑動視窗（長文案）
  const maxWinLen = isShort ? exp.length * SHORT_LINE_LEN_FACTOR : exp.length * 1.4;
  for (let i = 0; i < lines.length; i++) {
    let raw = '';
    for (let j = i; j < lines.length; j++) {
      raw += (raw ? ' ' : '') + lines[j];
      const win = normalizeText(raw);
      if (isShort && win.length > maxWinLen) break;
      const sim = scoreWindow(exp, win);
      let note = '';
      if (isShort && win.length > exp.length * 1.1) {
        note = '命中片段過長，可能為內文子串';
      }
      consider(i, j, sim, 'window', note);
      if (!isShort && win.length >= exp.length * 1.4) break;
    }
  }

  return best;
}
