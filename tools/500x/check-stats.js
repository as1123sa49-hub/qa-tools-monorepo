/**
 * 500X 遊戲機率分析工具
 * 檢查統計數據（對比 detail CSV 和 summary CSV）
 */

const fs = require('fs');
const path = require('path');

// 讀取 detail CSV（從 tools/500x/ 目錄，需要回到根目錄）
const detailPath = path.join(__dirname, '..', '..', 'reports', 'detail239.csv');
const detailContent = fs.readFileSync(detailPath, 'utf8');
const detailLines = detailContent.split('\n').filter(l => l.trim());
const detailHeaders = detailLines[0].split(',');

let bothSingle = 0;
let bothAny = 0;
let totalM2 = 0;
let totalM3 = 0;
let total807 = 0;
let total808 = 0;

for (let i = 1; i < detailLines.length; i++) {
  const line = detailLines[i];
  if (!line.trim()) continue;
  
  const parts = line.split(',');
  const bothSingleCol = parts[9]?.trim() || '';
  const bothAnyCol = parts[10]?.trim() || '';
  const m2Color = parts[1]?.trim() || '';
  const m3Color = parts[3]?.trim() || '';
  const adColor = parts[5]?.trim() || '';
  const atColor = parts[7]?.trim() || '';
  
  if (bothSingleCol === '是') bothSingle++;
  if (bothAnyCol === '是') bothAny++;
  
  if (m2Color && bothSingleCol === '否') totalM2++;
  if (m3Color && bothSingleCol === '否') totalM3++;
  if (adColor && bothAnyCol === '否') total807++;
  if (atColor && bothAnyCol === '否') total808++;
}

console.log('从 detail CSV 统计：');
console.log(`both_single_m2_m3: ${bothSingle}`);
console.log(`both_anyDouble_anyTriple: ${bothAny}`);
console.log(`total_single_m2: ${totalM2}`);
console.log(`total_single_m3: ${totalM3}`);
console.log(`total_anyDouble: ${total807}`);
console.log(`total_anyTriple: ${total808}`);

// 讀取 summary CSV
const summaryPath = path.join(__dirname, '..', '..', 'reports', 'summary239.csv');
const summaryContent = fs.readFileSync(summaryPath, 'utf8');
const summaryLines = summaryContent.split('\n').filter(l => l.trim());

console.log('\n从 summary CSV totals：');
for (const line of summaryLines) {
  if (line.startsWith('totals,')) {
    const parts = line.split(',');
    const type = parts[1]?.trim();
    const count = parts[4]?.trim();
    if (type && count) {
      console.log(`${type}: ${count}`);
    }
  }
}

