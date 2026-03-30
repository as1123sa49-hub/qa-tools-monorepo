/**
 * page-script.js — 在頁面 JS context 執行
 * 在 WebSocket 建立前替換 window.WebSocket，攔截所有 WS 訊息
 */
(function () {
  'use strict';

  if (window.__bonusV2Ext) return;
  window.__bonusV2Ext = true;

  // ─── V2 規格書期望值 ──────────────────────────────────────
  const V2_SPEC = {
    m2: {
      label: 'Single 2同',
      rates: [3, 4, 6, 8, 10],
      weights: { 3: 64, 4: 64, 6: 39, 8: 22, 10: 11 },
      total: 200
    },
    m3: {
      label: 'Single 3同',
      rates: [10, 20, 30, 60, 100],
      weights: { 10: 52, 20: 52, 30: 44, 60: 30, 100: 22 },
      total: 200
    },
    ad: {
      label: 'AnyDouble',
      rates: [2, 3, 5, 10, 20],
      weights: { 2: 86, 3: 57, 5: 33, 10: 16, 20: 8 },
      total: 200
    },
    at: {
      label: 'AnyTriple',
      rates: [50, 100, 150, 250, 500],
      weights: { 50: 100, 100: 49, 150: 30, 250: 14, 500: 7 },
      total: 200
    }
  };

  const COLOR_MAP = { 801: '黃', 802: '白', 803: '粉', 804: '藍', 805: '紅', 806: '綠' };

  // ─── 狀態 ─────────────────────────────────────────────────
  const state = {
    totalRounds: 0,
    m2: { total: 0, counts: {} },
    m3: { total: 0, counts: {} },
    ad: { total: 0, counts: {} },
    at: { total: 0, counts: {} },
    bonusType: { total: 0, m2: 0, m3: 0 },
    sidePool:  { total: 0, ad: 0, at: 0, both: 0 },
    drawCount: { ge1: 0, ge2: 0, ge3: 0, eq4: 0 }
  };
  const allRounds = [];
  const processedRounds = new Set();

  // ─── 解析電子骰資料 ───────────────────────────────────────
  function parseBonusData(data143) {
    const result = { single_m2: [], single_m3: [], any_double: null, any_triple: null };
    for (const [key, val] of Object.entries(data143)) {
      const k = Number(key);
      if (k >= 801 && k <= 806) {
        const color = COLOR_MAP[k] || String(k);
        if (val.matchColors === 2) result.single_m2.push({ color, rate: val.rate });
        else if (val.matchColors === 3) result.single_m3.push({ color, rate: val.rate });
      } else if (k === 807) {
        result.any_double = { color: COLOR_MAP[val.bonusColor] || String(val.bonusColor), rate: val.rate };
      } else if (k === 808) {
        result.any_triple = { color: COLOR_MAP[val.bonusColor] || String(val.bonusColor), rate: val.rate };
      }
    }
    return result;
  }

  // ─── 處理 WS 訊息 ─────────────────────────────────────────
  function processMessage(raw) {
    try {
      if (typeof raw !== 'string') return;
      if (raw.startsWith('$#|#$')) raw = raw.slice(5);
      if (!raw.startsWith('{')) return;

      const data = JSON.parse(raw);
      if (data.e !== 'notify' || data.d?.v?.[3] !== 'prepareBonusResult') return;

      const roundId = data.d?.v?.[10]?.[0];
      if (roundId && processedRounds.has(roundId)) return;
      if (roundId) processedRounds.add(roundId);

      const data143 = data.d?.v?.[10]?.[143];
      if (!data143 || typeof data143 !== 'object' || !Object.keys(data143).length) return;

      const parsed = parseBonusData(data143);
      state.totalRounds++;

      for (const item of (parsed.single_m2 || [])) {
        state.m2.total++;
        state.m2.counts[item.rate] = (state.m2.counts[item.rate] || 0) + 1;
      }
      for (const item of (parsed.single_m3 || [])) {
        state.m3.total++;
        state.m3.counts[item.rate] = (state.m3.counts[item.rate] || 0) + 1;
      }
      if (parsed.any_double) {
        state.ad.total++;
        const r = parsed.any_double.rate;
        state.ad.counts[r] = (state.ad.counts[r] || 0) + 1;
      }
      if (parsed.any_triple) {
        state.at.total++;
        const r = parsed.any_triple.rate;
        state.at.counts[r] = (state.at.counts[r] || 0) + 1;
      }

      allRounds.push({
        round: state.totalRounds,
        time: new Date().toLocaleTimeString('zh-TW', { hour12: false }),
        ...parsed
      });

      // CGBOV2-17：主注區獎勵類型
      for (let i = 0; i < (parsed.single_m2 || []).length; i++) {
        state.bonusType.total++; state.bonusType.m2++;
      }
      for (let i = 0; i < (parsed.single_m3 || []).length; i++) {
        state.bonusType.total++; state.bonusType.m3++;
      }

      // CGBOV2-18：旁注區獎勵類型
      const hasAD = !!parsed.any_double;
      const hasAT = !!parsed.any_triple;
      state.sidePool.total++;
      if (hasAD && hasAT)   state.sidePool.both++;
      else if (hasAD)       state.sidePool.ad++;
      else if (hasAT)       state.sidePool.at++;

      // CGBOV2-14：四次是否選顏色命中率
      const sc = (parsed.single_m2 || []).length + (parsed.single_m3 || []).length;
      if (sc >= 1) state.drawCount.ge1++;
      if (sc >= 2) state.drawCount.ge2++;
      if (sc >= 3) state.drawCount.ge3++;
      if (sc === 4) state.drawCount.eq4++;

      updatePanel();
      console.log(`%c[BonusV2] 已收集第 ${state.totalRounds} 局`, 'color:#51cf66;font-weight:bold');
    } catch (_) { /* 略過 */ }
  }

  // ─── 替換 window.WebSocket（在頁面 JS 執行前完成）────────
  const OrigWS = window.WebSocket;

  function PatchedWS(url, protocols) {
    const ws = protocols ? new OrigWS(url, protocols) : new OrigWS(url);
    ws.addEventListener('message', e => {
      if (typeof e.data === 'string') processMessage(e.data);
    });
    return ws;
  }

  // 繼承原始 WebSocket 的 prototype 與靜態屬性（setPrototypeOf 已自動繼承常數）
  PatchedWS.prototype = OrigWS.prototype;
  Object.setPrototypeOf(PatchedWS, OrigWS);

  window.WebSocket = PatchedWS;

  // ─── 面板樣式 ─────────────────────────────────────────────
  const PANEL_ID = '__bonusV2ExtPanel';

  const CSS = `
    #${PANEL_ID} {
      position: fixed; top: 20px; right: 20px; z-index: 2147483647;
      width: 390px; background: #1a1b1e; border: 1px solid #373a40;
      border-radius: 10px; box-shadow: 0 8px 32px rgba(0,0,0,.75);
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Microsoft JhengHei', sans-serif;
      font-size: 12px; color: #c9d1d9;
    }
    #${PANEL_ID} * { box-sizing: border-box; margin: 0; padding: 0; user-select: none; }
    #${PANEL_ID} .hdr {
      display: flex; justify-content: space-between; align-items: center;
      padding: 10px 14px; background: #25262b;
      border-radius: 10px 10px 0 0; border-bottom: 1px solid #373a40;
      cursor: move;
    }
    #${PANEL_ID} .hdr-l { display: flex; align-items: center; gap: 8px; }
    #${PANEL_ID} .title { font-weight: 700; font-size: 13px; color: #e9ecef; }
    #${PANEL_ID} .count { font-size: 11px; color: #51cf66; font-weight: 600; }
    #${PANEL_ID} .hdr-r { display: flex; gap: 6px; }
    #${PANEL_ID} .sm-btn {
      background: #373a40; border: none; color: #868e96;
      border-radius: 4px; padding: 3px 9px; font-size: 11px;
      cursor: pointer;
    }
    #${PANEL_ID} .sm-btn:hover { background: #495057; color: #dee2e6; }
    #${PANEL_ID} .body {
      padding: 10px 12px; max-height: 78vh; overflow-y: auto;
    }
    #${PANEL_ID} .sec { margin-bottom: 10px; }
    #${PANEL_ID} .sec-hdr {
      display: flex; justify-content: space-between; align-items: center;
      font-size: 11px; font-weight: 700; color: #74c0fc;
      padding-bottom: 5px; border-bottom: 1px solid #373a40; margin-bottom: 5px;
    }
    #${PANEL_ID} .sec-sub { font-weight: 400; color: #6e7681; font-size: 10px; }
    #${PANEL_ID} table { width: 100%; border-collapse: collapse; }
    #${PANEL_ID} th {
      text-align: right; padding: 2px 6px 4px;
      color: #6e7681; font-size: 10px; font-weight: 600;
      border-bottom: 1px solid #373a40;
    }
    #${PANEL_ID} th:first-child { text-align: left; }
    #${PANEL_ID} td {
      padding: 4px 6px; text-align: right;
      border-bottom: 1px solid #2c2e33; font-variant-numeric: tabular-nums;
    }
    #${PANEL_ID} td:first-child { text-align: left; font-weight: 600; }
    #${PANEL_ID} tr:last-child td { border-bottom: none; }
    #${PANEL_ID} .ok   { color: #51cf66; }
    #${PANEL_ID} .warn { color: #ffd43b; }
    #${PANEL_ID} .bad  { color: #ff6b6b; }
    #${PANEL_ID} .none { color: #6e7681; }
    #${PANEL_ID} .btn-row { display: flex; gap: 8px; margin-top: 10px; }
    #${PANEL_ID} .exp-btn {
      flex: 1; padding: 7px 0; background: #1971c2; color: #fff;
      border: none; border-radius: 6px; cursor: pointer;
      font-size: 11px; font-weight: 600;
    }
    #${PANEL_ID} .exp-btn:hover { background: #1864ab; }
    #${PANEL_ID} .clr-btn {
      padding: 7px 12px; background: #373a40; color: #dee2e6;
      border: none; border-radius: 6px; cursor: pointer; font-size: 11px;
    }
    #${PANEL_ID} .clr-btn:hover { background: #495057; }
    #${PANEL_ID} ::-webkit-scrollbar { width: 4px; }
    #${PANEL_ID} ::-webkit-scrollbar-thumb { background: #373a40; border-radius: 2px; }
  `;

  // ─── 建立面板 ─────────────────────────────────────────────
  function createPanel() {
    if (document.getElementById(PANEL_ID)) return;

    const style = document.createElement('style');
    style.textContent = CSS;
    document.head.appendChild(style);

    const panel = document.createElement('div');
    panel.id = PANEL_ID;

    const sections = ['m2', 'm3', 'ad', 'at'].map(key => {
      const rows = V2_SPEC[key].rates.map(rate => {
        const exp = (V2_SPEC[key].weights[rate] / V2_SPEC[key].total * 100).toFixed(1);
        return `<tr>
          <td>${rate}x</td>
          <td>${exp}%</td>
          <td id="__bv2e_cnt_${key}_${rate}">0</td>
          <td id="__bv2e_pct_${key}_${rate}">—</td>
          <td id="__bv2e_diff_${key}_${rate}" class="none">—</td>
        </tr>`;
      }).join('');

      return `<div class="sec">
        <div class="sec-hdr">
          <span>▌ ${V2_SPEC[key].label}</span>
          <span class="sec-sub" id="__bv2e_sub_${key}">共 0 次</span>
        </div>
        <table>
          <thead><tr>
            <th>倍率</th><th>期望%</th><th>次數</th><th>實際%</th><th>差值</th>
          </tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>`;
    }).join('');

    const extraSections = `
      <div class="sec">
        <div class="sec-hdr">
          <span>▌ 主注區獎勵類型</span>
          <span class="sec-sub" id="__bv2e_sub_bt">共 0 次</span>
        </div>
        <table>
          <thead><tr><th>類型</th><th>期望%</th><th>次數</th><th>實際%</th><th>差值</th></tr></thead>
          <tbody>
            <tr>
              <td>2同</td><td>33.3%</td>
              <td id="__bv2e_cnt_bt_m2">0</td>
              <td id="__bv2e_pct_bt_m2">—</td>
              <td id="__bv2e_diff_bt_m2" class="none">—</td>
            </tr>
            <tr>
              <td>3同</td><td>66.7%</td>
              <td id="__bv2e_cnt_bt_m3">0</td>
              <td id="__bv2e_pct_bt_m3">—</td>
              <td id="__bv2e_diff_bt_m3" class="none">—</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="sec">
        <div class="sec-hdr">
          <span>▌ 旁注區獎勵類型</span>
          <span class="sec-sub" id="__bv2e_sub_sp">共 0 局</span>
        </div>
        <table>
          <thead><tr><th>類型</th><th>期望%</th><th>次數</th><th>實際%</th><th>差值</th></tr></thead>
          <tbody>
            <tr>
              <td>AD 池</td><td>40.0%</td>
              <td id="__bv2e_cnt_sp_ad">0</td>
              <td id="__bv2e_pct_sp_ad">—</td>
              <td id="__bv2e_diff_sp_ad" class="none">—</td>
            </tr>
            <tr>
              <td>AT 池</td><td>31.0%</td>
              <td id="__bv2e_cnt_sp_at">0</td>
              <td id="__bv2e_pct_sp_at">—</td>
              <td id="__bv2e_diff_sp_at" class="none">—</td>
            </tr>
            <tr>
              <td>Both</td><td>29.0%</td>
              <td id="__bv2e_cnt_sp_both">0</td>
              <td id="__bv2e_pct_sp_both">—</td>
              <td id="__bv2e_diff_sp_both" class="none">—</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="sec">
        <div class="sec-hdr">
          <span>▌ 四次是否選顏色命中率</span>
          <span class="sec-sub" id="__bv2e_sub_dc">共 0 局</span>
        </div>
        <table>
          <thead><tr><th>抽次</th><th>期望%</th><th>母數</th><th>命中</th><th>實際%</th><th>差值</th></tr></thead>
          <tbody>
            <tr>
              <td>第一抽</td><td>96%</td>
              <td id="__bv2e_base_dc_1">0</td><td id="__bv2e_cnt_dc_1">0</td>
              <td id="__bv2e_pct_dc_1">—</td>
              <td id="__bv2e_diff_dc_1" class="none">—</td>
            </tr>
            <tr>
              <td>第二抽</td><td>79%</td>
              <td id="__bv2e_base_dc_2">0</td><td id="__bv2e_cnt_dc_2">0</td>
              <td id="__bv2e_pct_dc_2">—</td>
              <td id="__bv2e_diff_dc_2" class="none">—</td>
            </tr>
            <tr>
              <td>第三抽</td><td>53%</td>
              <td id="__bv2e_base_dc_3">0</td><td id="__bv2e_cnt_dc_3">0</td>
              <td id="__bv2e_pct_dc_3">—</td>
              <td id="__bv2e_diff_dc_3" class="none">—</td>
            </tr>
            <tr>
              <td>第四抽</td><td>12%</td>
              <td id="__bv2e_base_dc_4">0</td><td id="__bv2e_cnt_dc_4">0</td>
              <td id="__bv2e_pct_dc_4">—</td>
              <td id="__bv2e_diff_dc_4" class="none">—</td>
            </tr>
          </tbody>
        </table>
      </div>`;

    panel.innerHTML = `
      <div class="hdr" id="__bv2e_hdr">
        <div class="hdr-l">
          <span class="title">🎲 Bonus V2 電子骰驗證</span>
          <span class="count" id="__bv2e_count">0 局</span>
        </div>
        <div class="hdr-r">
          <button class="sm-btn" id="__bv2e_min">—</button>
        </div>
      </div>
      <div class="body" id="__bv2e_body">
        ${sections}
        ${extraSections}
        <div class="btn-row">
          <button class="exp-btn" id="__bv2e_stats">📊 統計 CSV</button>
          <button class="exp-btn" id="__bv2e_detail">📋 明細 CSV</button>
          <button class="clr-btn" id="__bv2e_clear">清空</button>
        </div>
      </div>`;

    document.body.appendChild(panel);
    bindEvents(panel);
  }

  // ─── 更新面板數據 ─────────────────────────────────────────
  function updatePanel() {
    const countEl = document.getElementById('__bv2e_count');
    if (countEl) countEl.textContent = `${state.totalRounds} 局`;

    for (const key of ['m2', 'm3', 'ad', 'at']) {
      const cat  = state[key];
      const spec = V2_SPEC[key];

      const sub = document.getElementById(`__bv2e_sub_${key}`);
      if (sub) sub.textContent = `共 ${cat.total} 次`;

      for (const rate of spec.rates) {
        const count  = cat.counts[rate] || 0;
        const cntEl  = document.getElementById(`__bv2e_cnt_${key}_${rate}`);
        const pctEl  = document.getElementById(`__bv2e_pct_${key}_${rate}`);
        const diffEl = document.getElementById(`__bv2e_diff_${key}_${rate}`);
        if (!cntEl) continue;

        cntEl.textContent = count;

        if (cat.total === 0) {
          pctEl.textContent = '—'; diffEl.textContent = '—'; diffEl.className = 'none';
          continue;
        }

        const ap   = count / cat.total * 100;
        const ep   = spec.weights[rate] / spec.total * 100;
        const diff = ap - ep;
        const abs  = Math.abs(diff);

        pctEl.textContent  = ap.toFixed(1) + '%';
        diffEl.textContent = (diff >= 0 ? '+' : '') + diff.toFixed(1) + '%';
        diffEl.className   = abs < 5 ? 'ok' : abs < 10 ? 'warn' : 'bad';
      }
    }
    updateExtraCards();
  }

  // ─── 更新新統計區塊 ───────────────────────────────────────
  function updateExtraCards() {
    // 主注區獎勵類型
    const bt = state.bonusType;
    const subBt = document.getElementById('__bv2e_sub_bt');
    if (subBt) subBt.textContent = `共 ${bt.total} 次`;
    for (const { id, count, expected } of [
      { id: 'm2', count: bt.m2, expected: 100 / 3 },
      { id: 'm3', count: bt.m3, expected: 200 / 3 }
    ]) {
      const cntEl  = document.getElementById(`__bv2e_cnt_bt_${id}`);
      const pctEl  = document.getElementById(`__bv2e_pct_bt_${id}`);
      const diffEl = document.getElementById(`__bv2e_diff_bt_${id}`);
      if (!cntEl) continue;
      cntEl.textContent = count;
      if (bt.total === 0) { pctEl.textContent = '—'; diffEl.textContent = '—'; diffEl.className = 'none'; continue; }
      const ap = count / bt.total * 100, diff = ap - expected, abs = Math.abs(diff);
      pctEl.textContent  = ap.toFixed(1) + '%';
      diffEl.textContent = (diff >= 0 ? '+' : '') + diff.toFixed(1) + '%';
      diffEl.className   = abs < 5 ? 'ok' : abs < 10 ? 'warn' : 'bad';
    }

    // 旁注區獎勵類型
    const sp = state.sidePool;
    const subSp = document.getElementById('__bv2e_sub_sp');
    if (subSp) subSp.textContent = `共 ${sp.total} 局`;
    for (const { id, count, expected } of [
      { id: 'ad',   count: sp.ad,   expected: 40 },
      { id: 'at',   count: sp.at,   expected: 31 },
      { id: 'both', count: sp.both, expected: 29 }
    ]) {
      const cntEl  = document.getElementById(`__bv2e_cnt_sp_${id}`);
      const pctEl  = document.getElementById(`__bv2e_pct_sp_${id}`);
      const diffEl = document.getElementById(`__bv2e_diff_sp_${id}`);
      if (!cntEl) continue;
      cntEl.textContent = count;
      if (sp.total === 0) { pctEl.textContent = '—'; diffEl.textContent = '—'; diffEl.className = 'none'; continue; }
      const ap = count / sp.total * 100, diff = ap - expected, abs = Math.abs(diff);
      pctEl.textContent  = ap.toFixed(1) + '%';
      diffEl.textContent = (diff >= 0 ? '+' : '') + diff.toFixed(1) + '%';
      diffEl.className   = abs < 5 ? 'ok' : abs < 10 ? 'warn' : 'bad';
    }

    // 四次是否選顏色命中率
    const dc = state.drawCount;
    const subDc = document.getElementById('__bv2e_sub_dc');
    if (subDc) subDc.textContent = `共 ${state.totalRounds} 局`;
    for (const { n, base, hit, expected } of [
      { n: 1, base: state.totalRounds, hit: dc.ge1, expected: 96 },
      { n: 2, base: dc.ge1,            hit: dc.ge2, expected: 79 },
      { n: 3, base: dc.ge2,            hit: dc.ge3, expected: 53 },
      { n: 4, base: dc.ge3,            hit: dc.eq4, expected: 12 }
    ]) {
      const baseEl = document.getElementById(`__bv2e_base_dc_${n}`);
      const cntEl  = document.getElementById(`__bv2e_cnt_dc_${n}`);
      const pctEl  = document.getElementById(`__bv2e_pct_dc_${n}`);
      const diffEl = document.getElementById(`__bv2e_diff_dc_${n}`);
      if (!baseEl) continue;
      baseEl.textContent = base;
      cntEl.textContent  = hit;
      if (base === 0) { pctEl.textContent = '—'; diffEl.textContent = '—'; diffEl.className = 'none'; continue; }
      const ap = hit / base * 100, diff = ap - expected, abs = Math.abs(diff);
      pctEl.textContent  = ap.toFixed(1) + '%';
      diffEl.textContent = (diff >= 0 ? '+' : '') + diff.toFixed(1) + '%';
      diffEl.className   = abs < 5 ? 'ok' : abs < 10 ? 'warn' : 'bad';
    }
  }

  // ─── CSV 匯出 ─────────────────────────────────────────────
  function downloadCSV(rows, filename) {
    const lines = rows.map(r =>
      r.map(c => {
        const s = String(c ?? '').replace(/"/g, '""');
        return /[,"\n]/.test(s) ? `"${s}"` : s;
      }).join(',')
    );
    const blob = new Blob(['\uFEFF' + lines.join('\n')], { type: 'text/csv' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  function exportStats() {
    const rows = [['類別', '倍率', '權重', '期望%', '實際次數', '實際%', '差值%', '狀態']];
    for (const [key, spec] of Object.entries(V2_SPEC)) {
      const cat = state[key];
      for (const rate of spec.rates) {
        const count = cat.counts[rate] || 0;
        const ep = (spec.weights[rate] / spec.total * 100).toFixed(2);
        let ap = '—', diff = '—', status = '—';
        if (cat.total > 0) {
          const a = count / cat.total * 100;
          const d = a - spec.weights[rate] / spec.total * 100;
          ap = a.toFixed(2);
          diff = (d >= 0 ? '+' : '') + d.toFixed(2);
          status = Math.abs(d) < 5 ? '正常' : Math.abs(d) < 10 ? '留意' : '偏差';
        }
        rows.push([spec.label, `${rate}x`, spec.weights[rate], `${ep}%`, count,
          cat.total > 0 ? `${ap}%` : '—', cat.total > 0 ? `${diff}%` : '—', status]);
      }
    }
    // CGBOV2-17：主注區獎勵類型
    rows.push(['', '', '', '', '', '', '', '']);
    const bt = state.bonusType;
    for (const { label, count, expected } of [
      { label: '2同', count: bt.m2, expected: 100 / 3 },
      { label: '3同', count: bt.m3, expected: 200 / 3 }
    ]) {
      let ap = '—', diff = '—', status = '—';
      if (bt.total > 0) {
        const a = count / bt.total * 100, d = a - expected;
        ap = a.toFixed(2); diff = (d >= 0 ? '+' : '') + d.toFixed(2);
        status = Math.abs(d) < 5 ? '正常' : Math.abs(d) < 10 ? '留意' : '偏差';
      }
      rows.push(['主注區獎勵類型', label, '—', expected.toFixed(2) + '%', count,
        bt.total > 0 ? ap + '%' : '—', bt.total > 0 ? diff + '%' : '—', status]);
    }

    // CGBOV2-18：旁注區獎勵類型
    rows.push(['', '', '', '', '', '', '', '']);
    const sp = state.sidePool;
    for (const { label, count, expected } of [
      { label: 'AD 池', count: sp.ad,   expected: 40 },
      { label: 'AT 池', count: sp.at,   expected: 31 },
      { label: 'Both',  count: sp.both, expected: 29 }
    ]) {
      let ap = '—', diff = '—', status = '—';
      if (sp.total > 0) {
        const a = count / sp.total * 100, d = a - expected;
        ap = a.toFixed(2); diff = (d >= 0 ? '+' : '') + d.toFixed(2);
        status = Math.abs(d) < 5 ? '正常' : Math.abs(d) < 10 ? '留意' : '偏差';
      }
      rows.push(['旁注區獎勵類型', label, '—', expected.toFixed(2) + '%', count,
        sp.total > 0 ? ap + '%' : '—', sp.total > 0 ? diff + '%' : '—', status]);
    }

    // CGBOV2-14：四次是否選顏色命中率
    rows.push(['', '', '', '', '', '', '', '']);
    const dc = state.drawCount;
    for (const { label, base, hit, expected } of [
      { label: '第一抽', base: state.totalRounds, hit: dc.ge1, expected: 96 },
      { label: '第二抽', base: dc.ge1,            hit: dc.ge2, expected: 79 },
      { label: '第三抽', base: dc.ge2,            hit: dc.ge3, expected: 53 },
      { label: '第四抽', base: dc.ge3,            hit: dc.eq4, expected: 12 }
    ]) {
      let ap = '—', diff = '—', status = '—';
      if (base > 0) {
        const a = hit / base * 100, d = a - expected;
        ap = a.toFixed(2); diff = (d >= 0 ? '+' : '') + d.toFixed(2);
        status = Math.abs(d) < 5 ? '正常' : Math.abs(d) < 10 ? '留意' : '偏差';
      }
      rows.push(['四次是否選顏色命中率', label, `母數 ${base} / 命中 ${hit}`,
        expected.toFixed(2) + '%', hit,
        base > 0 ? ap + '%' : '—', base > 0 ? diff + '%' : '—', status]);
    }

    downloadCSV(rows, `bonus_v2_stats_${Date.now()}.csv`);
  }

  function exportDetail() {
    const rows = [['局號', '時間', 'Single_M2_顏色', 'Single_M2_倍率',
      'Single_M3_顏色', 'Single_M3_倍率', 'AnyDouble_顏色', 'AnyDouble_倍率',
      'AnyTriple_顏色', 'AnyTriple_倍率']];
    for (const r of allRounds) {
      rows.push([
        r.round, r.time,
        (r.single_m2 || []).map(i => i.color).join(';'),
        (r.single_m2 || []).map(i => i.rate).join(';'),
        (r.single_m3 || []).map(i => i.color).join(';'),
        (r.single_m3 || []).map(i => i.rate).join(';'),
        r.any_double?.color ?? '', r.any_double?.rate ?? '',
        r.any_triple?.color ?? '', r.any_triple?.rate ?? ''
      ]);
    }
    downloadCSV(rows, `bonus_v2_detail_${Date.now()}.csv`);
  }

  // ─── 按鈕事件 ─────────────────────────────────────────────
  function bindEvents(panel) {
    let collapsed = false;
    document.getElementById('__bv2e_min').addEventListener('click', () => {
      const body = document.getElementById('__bv2e_body');
      collapsed = !collapsed;
      body.style.display = collapsed ? 'none' : 'block';
      document.getElementById('__bv2e_min').textContent = collapsed ? '＋' : '—';
    });

    document.getElementById('__bv2e_clear').addEventListener('click', () => {
      Object.assign(state, {
        totalRounds: 0,
        m2: { total: 0, counts: {} }, m3: { total: 0, counts: {} },
        ad: { total: 0, counts: {} }, at: { total: 0, counts: {} },
        bonusType: { total: 0, m2: 0, m3: 0 },
        sidePool:  { total: 0, ad: 0, at: 0, both: 0 },
        drawCount: { ge1: 0, ge2: 0, ge3: 0, eq4: 0 }
      });
      allRounds.length = 0;
      processedRounds.clear();
      updatePanel();
    });

    document.getElementById('__bv2e_stats').addEventListener('click', exportStats);
    document.getElementById('__bv2e_detail').addEventListener('click', exportDetail);

    // 可拖曳
    let dragging = false, ox = 0, oy = 0;
    document.getElementById('__bv2e_hdr').addEventListener('mousedown', e => {
      dragging = true;
      ox = e.clientX - panel.offsetLeft;
      oy = e.clientY - panel.offsetTop;
      e.preventDefault();
    });
    document.addEventListener('mousemove', e => {
      if (!dragging) return;
      panel.style.right = 'auto';
      panel.style.left  = Math.max(0, e.clientX - ox) + 'px';
      panel.style.top   = Math.max(0, e.clientY - oy) + 'px';
    });
    document.addEventListener('mouseup', () => { dragging = false; });

    panel.addEventListener('click',     e => e.stopPropagation());
    panel.addEventListener('mousedown', e => e.stopPropagation());
  }

  // ─── 面板建立與持續守護 ───────────────────────────────────
  let panelGuard = null;

  function tryCreatePanel() {
    if (document.getElementById('__bonusV2ExtPanel')) return;
    if (!document.body) return;
    createPanel();

    // 建立後啟動守護：若面板被遊戲框架移除則自動補回
    if (panelGuard) panelGuard.disconnect();
    panelGuard = new MutationObserver(() => {
      if (!document.getElementById('__bonusV2ExtPanel') && document.body) {
        createPanel();
      }
    });
    panelGuard.observe(document.body, { childList: true });
  }

  // 機制 1：body 已存在 → 延遲 2 秒等遊戲框架掛載完成
  if (document.body) {
    setTimeout(tryCreatePanel, 2000);
  } else {
    // 機制 2：DOMContentLoaded 監聽（延遲 2 秒）
    document.addEventListener('DOMContentLoaded', () => setTimeout(tryCreatePanel, 2000));

    // 機制 3：MutationObserver 觀察 html，等 body 插入後延遲 2 秒
    const bodyObserver = new MutationObserver(() => {
      if (document.body) {
        bodyObserver.disconnect();
        setTimeout(tryCreatePanel, 2000);
      }
    });
    bodyObserver.observe(document.documentElement, { childList: true });

    // 機制 4：輪詢備援（每 200ms，最多等 30 秒），body 出現後延遲 2 秒
    let pollCount = 0;
    const pollTimer = setInterval(() => {
      pollCount++;
      if (document.getElementById('__bonusV2ExtPanel')) {
        clearInterval(pollTimer);
      } else if (document.body) {
        clearInterval(pollTimer);
        setTimeout(tryCreatePanel, 2000);
      } else if (pollCount >= 150) {
        clearInterval(pollTimer);
      }
    }, 200);
  }

  console.log('%c✅ [Bonus V2] 電子骰機率驗證 Extension 已啟動', 'color:#51cf66;font-weight:bold;font-size:13px');
})();
