/**
 * 500X 遊戲機率分析工具
 * 驗證倍率統計（按倍率匯總）
 */

const fs = require('fs');
const path = require('path');

// 讀取 detail CSV（從 tools/500x/ 目錄，需要回到根目錄）
const detailPath = path.join(__dirname, '..', '..', 'reports', 'detail239.csv');
const detailContent = fs.readFileSync(detailPath, 'utf8');
const detailLines = detailContent.split('\n').filter(l => l.trim());

// 统计包含 both 的情况（图片中的统计方式）
const stats = {
  m2: {},
  m3: {},
  ad: {},
  at: {}
};

for (let i = 1; i < detailLines.length; i++) {
  const line = detailLines[i];
  if (!line.trim()) continue;
  
  const parts = line.split(',');
  const m2Color = parts[1]?.trim() || '';
  const m2Rate = parts[2]?.trim() || '';
  const m3Color = parts[3]?.trim() || '';
  const m3Rate = parts[4]?.trim() || '';
  const adColor = parts[5]?.trim() || '';
  const adRate = parts[6]?.trim() || '';
  const atColor = parts[7]?.trim() || '';
  const atRate = parts[8]?.trim() || '';
  
  // 统计 m2（包含 both 情况）
  if (m2Color && m2Rate) {
    stats.m2[m2Rate] = (stats.m2[m2Rate] || 0) + 1;
  }
  
  // 统计 m3（包含 both 情况）
  if (m3Color && m3Rate) {
    stats.m3[m3Rate] = (stats.m3[m3Rate] || 0) + 1;
  }
  
  // 统计 anyDouble（包含 both 情况）
  if (adColor && adRate) {
    stats.ad[adRate] = (stats.ad[adRate] || 0) + 1;
  }
  
  // 统计 anyTriple（包含 both 情况）
  if (atColor && atRate) {
    stats.at[atRate] = (stats.at[atRate] || 0) + 1;
  }
}

console.log('从 detail CSV 统计（包含 both 情况）：');
console.log('\nSingle M2 by Rate:');
for (const rate of Object.keys(stats.m2).sort((a,b) => Number(a) - Number(b))) {
  console.log(`  ${rate}x: ${stats.m2[rate]}`);
}

console.log('\nSingle M3 by Rate:');
for (const rate of Object.keys(stats.m3).sort((a,b) => Number(a) - Number(b))) {
  console.log(`  ${rate}x: ${stats.m3[rate]}`);
}

console.log('\nAnyDouble by Rate:');
for (const rate of Object.keys(stats.ad).sort((a,b) => Number(a) - Number(b))) {
  console.log(`  ${rate}x: ${stats.ad[rate]}`);
}

console.log('\nAnyTriple by Rate:');
for (const rate of Object.keys(stats.at).sort((a,b) => Number(a) - Number(b))) {
  console.log(`  ${rate}x: ${stats.at[rate]}`);
}

// 讀取 summary CSV
const summaryPath = path.join(__dirname, '..', '..', 'reports', 'summary239.csv');
const summaryContent = fs.readFileSync(summaryPath, 'utf8');
const summaryLines = summaryContent.split('\n').filter(l => l.trim());

console.log('\n\n从 summary CSV 统计（排除 both 情况）：');
let inSection = '';
let sectionStats = {};

for (const line of summaryLines) {
  if (line.startsWith('single_m2_byRate,')) {
    inSection = 'm2';
    sectionStats = {};
    continue;
  }
  if (line.startsWith('single_m3_byRate,')) {
    inSection = 'm3';
    sectionStats = {};
    continue;
  }
  if (line.startsWith('anyDouble_byRate,')) {
    inSection = 'ad';
    sectionStats = {};
    continue;
  }
  if (line.startsWith('anyTriple_byRate,')) {
    inSection = 'at';
    sectionStats = {};
    continue;
  }
  
  if (inSection && line.startsWith('single_m2_byRate,')) continue;
  if (inSection && line.startsWith('single_m3_byRate,')) continue;
  if (inSection && line.startsWith('anyDouble_byRate,')) continue;
  if (inSection && line.startsWith('anyTriple_byRate,')) continue;
  
  if (inSection && line.includes(',')) {
    const parts = line.split(',');
    if (parts[0] === 'rate' || parts[0] === 'single_m2_byRate' || parts[0] === 'single_m3_byRate' || 
        parts[0] === 'anyDouble_byRate' || parts[0] === 'anyTriple_byRate') {
      continue;
    }
    const rate = parts[1]?.trim();
    const count = parts[2]?.trim();
    if (rate && count) {
      sectionStats[rate] = count;
    }
  }
  
  if (inSection && (line.startsWith('single_m2_byColor,') || line.startsWith('single_m3_byColor,') || 
      line.startsWith('anyDouble_byColor,') || line.startsWith('anyTriple_byColor,'))) {
    if (inSection === 'm2') {
      console.log('\nSingle M2 by Rate (summary):');
      for (const rate of Object.keys(sectionStats).sort((a,b) => Number(a) - Number(b))) {
        console.log(`  ${rate}x: ${sectionStats[rate]}`);
      }
    } else if (inSection === 'm3') {
      console.log('\nSingle M3 by Rate (summary):');
      for (const rate of Object.keys(sectionStats).sort((a,b) => Number(a) - Number(b))) {
        console.log(`  ${rate}x: ${sectionStats[rate]}`);
      }
    } else if (inSection === 'ad') {
      console.log('\nAnyDouble by Rate (summary):');
      for (const rate of Object.keys(sectionStats).sort((a,b) => Number(a) - Number(b))) {
        console.log(`  ${rate}x: ${sectionStats[rate]}`);
      }
    } else if (inSection === 'at') {
      console.log('\nAnyTriple by Rate (summary):');
      for (const rate of Object.keys(sectionStats).sort((a,b) => Number(a) - Number(b))) {
        console.log(`  ${rate}x: ${sectionStats[rate]}`);
      }
    }
    inSection = '';
    sectionStats = {};
  }
}

// 最后输出 anyTriple
if (inSection === 'at' && Object.keys(sectionStats).length > 0) {
  console.log('\nAnyTriple by Rate (summary):');
  for (const rate of Object.keys(sectionStats).sort((a,b) => Number(a) - Number(b))) {
    console.log(`  ${rate}x: ${sectionStats[rate]}`);
  }
}

