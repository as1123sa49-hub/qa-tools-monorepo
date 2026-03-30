/**
 * 500X 遊戲機率分析工具
 * 計算預期機率並與實際統計對比
 */

const fs = require('fs');
const path = require('path');

// 從圖片中獲取的權重數據
const weights = {
  m2: {
    '801': 99,  // 黃
    '802': 66,  // 白
    '803': 15,  // 粉
    '804': 12,  // 藍
    '805': 8,   // 紅
    '806': 8    // 綠
  },
  m3: {
    '801': 99,  // 黃
    '802': 66,  // 白
    '803': 15,  // 粉
    '804': 12,  // 藍
    '805': 8,   // 紅
    '806': 8    // 綠
  }
};

// 計算總權重
const totalWeight = 200; // 99+66+15+12+8+8 = 200

// 讀取 summary CSV（從 tools/500x/ 目錄，需要回到根目錄）
const summaryPath = path.join(__dirname, '..', '..', 'reports', 'dice-500x-CG500X-summary.csv');
const summaryContent = fs.readFileSync(summaryPath, 'utf8');
const summaryLines = summaryContent.split('\n').filter(l => l.trim());

// 讀取實際統計
const actualStats = {
  m2: {},
  m3: {}
};

// 找到 single_m2_byColor 和 single_m3_byColor 的行
for (let i = 0; i < summaryLines.length; i++) {
  const line = summaryLines[i];
  if (line.startsWith('single_m2_byColor,color,')) {
    // 讀取下一行開始的數據
    for (let j = i + 1; j < summaryLines.length; j++) {
      const dataLine = summaryLines[j];
      if (dataLine.startsWith('single_m2_byColor,')) {
        const parts = dataLine.split(',');
        if (parts.length >= 4) {
          const colorId = parts[2]?.trim();
          const count = Number(parts[3]?.trim() || 0);
          if (colorId && count > 0 && ['801','802','803','804','805','806'].includes(colorId)) {
            actualStats.m2[colorId] = count;
          }
        }
      } else if (dataLine.startsWith('single_m3_byColor,color,')) {
        break;
      }
    }
  }
  if (line.startsWith('single_m3_byColor,color,')) {
    // 讀取下一行開始的數據
    for (let j = i + 1; j < summaryLines.length; j++) {
      const dataLine = summaryLines[j];
      if (dataLine.startsWith('single_m3_byColor,')) {
        const parts = dataLine.split(',');
        if (parts.length >= 4) {
          const colorId = parts[2]?.trim();
          const count = Number(parts[3]?.trim() || 0);
          if (colorId && count > 0 && ['801','802','803','804','805','806'].includes(colorId)) {
            actualStats.m3[colorId] = count;
          }
        }
      } else if (dataLine.startsWith('anyDouble_byColor,color,')) {
        break;
      }
    }
  }
}

const areaToZh = { '801': '黃', '802': '白', '803': '粉', '804': '藍', '805': '紅', '806': '綠' };

// 計算並顯示結果
console.log('='.repeat(60));
console.log('Single M2 (2個相同顏色) - 預期機率計算');
console.log('='.repeat(60));

let m2Total = 0;
for (const colorId of ['801','802','803','804','805','806']) {
  m2Total += actualStats.m2[colorId] || 0;
}

console.log(`\n總次數: ${m2Total}`);
console.log(`總權重: ${totalWeight}\n`);

console.log('顏色\t實際次數\t權重\t權重占比\t預期次數\t實際/預期');
console.log('-'.repeat(60));

for (const colorId of ['801','802','803','804','805','806']) {
  const actual = actualStats.m2[colorId] || 0;
  const weight = weights.m2[colorId];
  const weightPercent = (weight / totalWeight * 100).toFixed(2);
  const expected = (m2Total * weight / totalWeight).toFixed(2);
  const ratio = Number(expected) > 0 ? (actual / Number(expected)).toFixed(2) : '0.00';
  
  console.log(`${areaToZh[colorId]}\t${actual}\t\t${weight}\t${weightPercent}%\t\t${expected}\t\t${ratio}`);
}

console.log('\n' + '='.repeat(60));
console.log('Single M3 (3個相同顏色) - 預期機率計算');
console.log('='.repeat(60));

let m3Total = 0;
for (const colorId of ['801','802','803','804','805','806']) {
  m3Total += actualStats.m3[colorId] || 0;
}

console.log(`\n總次數: ${m3Total}`);
console.log(`總權重: ${totalWeight}\n`);

console.log('顏色\t實際次數\t權重\t權重占比\t預期次數\t實際/預期');
console.log('-'.repeat(60));

for (const colorId of ['801','802','803','804','805','806']) {
  const actual = actualStats.m3[colorId] || 0;
  const weight = weights.m3[colorId];
  const weightPercent = (weight / totalWeight * 100).toFixed(2);
  const expected = (m3Total * weight / totalWeight).toFixed(2);
  const ratio = Number(expected) > 0 ? (actual / Number(expected)).toFixed(2) : '0.00';
  
  console.log(`${areaToZh[colorId]}\t${actual}\t\t${weight}\t${weightPercent}%\t\t${expected}\t\t${ratio}`);
}

console.log('\n計算公式說明：');
console.log('預期次數 = 總次數 × (權重 / 總權重)');
console.log('實際/預期 = 實際次數 / 預期次數（越接近 1.00 表示越符合預期）');

