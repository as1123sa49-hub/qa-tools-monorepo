/**
 * 500X 遊戲機率分析工具
 * 檢查顏色統計（按顏色匯總）
 */

const fs = require('fs');
const path = require('path');

// 讀取 detail CSV（從 tools/500x/ 目錄，需要回到根目錄）
const detailPath = path.join(__dirname, '..', '..', 'reports', 'detail239.csv');
const detailContent = fs.readFileSync(detailPath, 'utf8');
const detailLines = detailContent.split('\n').filter(l => l.trim());

const zhToArea = { '黃': '801', '白': '802', '粉': '803', '藍': '804', '紅': '805', '綠': '806' };
const areaToZh = { '801': '黃', '802': '白', '803': '粉', '804': '藍', '805': '紅', '806': '綠' };

const stats = {
  m2: {},
  m3: {},
  ad: {},
  at: {}
};

for (let i = 1; i < detailLines.length; i++) {
  const line = detailLines[i];
  if (!line.trim()) continue;
  
  const parts = line.split(',').map(p => p.trim().replace(/^"|"$/g, ''));
  const m2ColorZh = parts[1]?.trim() || '';
  const m3ColorZh = parts[3]?.trim() || '';
  const adColorZh = parts[5]?.trim() || '';
  const atColorZh = parts[7]?.trim() || '';
  
  // 统计 m2（包含 both 情况）
  if (m2ColorZh && zhToArea[m2ColorZh]) {
    const colorId = zhToArea[m2ColorZh];
    stats.m2[colorId] = (stats.m2[colorId] || 0) + 1;
  }
  
  // 统计 m3（包含 both 情况）
  if (m3ColorZh && zhToArea[m3ColorZh]) {
    const colorId = zhToArea[m3ColorZh];
    stats.m3[colorId] = (stats.m3[colorId] || 0) + 1;
  }
  
  // 统计 anyDouble（包含 both 情况）
  if (adColorZh && zhToArea[adColorZh]) {
    const colorId = zhToArea[adColorZh];
    stats.ad[colorId] = (stats.ad[colorId] || 0) + 1;
  }
  
  // 统计 anyTriple（包含 both 情况）
  if (atColorZh && zhToArea[atColorZh]) {
    const colorId = zhToArea[atColorZh];
    stats.at[colorId] = (stats.at[colorId] || 0) + 1;
  }
}

console.log('从 detail CSV 统计（包含 both 情况）：');
console.log('\nSingle M2 by Color:');
let m2Total = 0;
for (const colorId of ['801','802','803','804','805','806']) {
  const count = stats.m2[colorId] || 0;
  if (count > 0) {
    console.log(`  ${areaToZh[colorId]}(${colorId}): ${count}`);
    m2Total += count;
  }
}
console.log(`  總和: ${m2Total}`);

console.log('\nSingle M3 by Color:');
let m3Total = 0;
for (const colorId of ['801','802','803','804','805','806']) {
  const count = stats.m3[colorId] || 0;
  if (count > 0) {
    console.log(`  ${areaToZh[colorId]}(${colorId}): ${count}`);
    m3Total += count;
  }
}
console.log(`  總和: ${m3Total}`);

console.log('\nAnyDouble by Color:');
let adTotal = 0;
for (const colorId of ['801','802','803','804','805','806']) {
  const count = stats.ad[colorId] || 0;
  if (count > 0) {
    console.log(`  ${areaToZh[colorId]}(${colorId}): ${count}`);
    adTotal += count;
  }
}
console.log(`  總和: ${adTotal}`);

console.log('\nAnyTriple by Color:');
let atTotal = 0;
for (const colorId of ['801','802','803','804','805','806']) {
  const count = stats.at[colorId] || 0;
  if (count > 0) {
    console.log(`  ${areaToZh[colorId]}(${colorId}): ${count}`);
    atTotal += count;
  }
}
console.log(`  總和: ${atTotal}`);

console.log('\n\nSummary:');
console.log(`single_m2 總和: ${m2Total}`);
console.log(`single_m3 總和: ${m3Total}`);
console.log(`anyDouble 總和: ${adTotal}`);
console.log(`anyTriple 總和: ${atTotal}`);

