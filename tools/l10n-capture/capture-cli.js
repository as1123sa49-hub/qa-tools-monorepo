#!/usr/bin/env node
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { runSlotCapture, saveAuthInteractive, loadConfig } from './lib/capture-flow.js';
import { loadKeysFromSheet, listLangsFromXlsx } from './lib/xlsx-node.js';
import { slotToSheet } from './lib/slot-sheet.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

function parseArgs(argv) {
  const args = { _: [] };
  for (let i = 2; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--save-auth') args.saveAuth = true;
    else if (a === '--env') args.env = argv[++i];
    else if (a === '--lang') args.lang = argv[++i];
    else if (a === '--all-langs') args.allLangs = true;
    else if (a === '--slot') args.slots = (argv[++i] || '').split(',').map(s => s.trim()).filter(Boolean);
    else if (a === '--xlsx') args.xlsx = argv[++i];
    else if (a === '--sheet') args.sheet = argv[++i];
    else args._.push(a);
  }
  return args;
}

async function main() {
  const args = parseArgs(process.argv);

  if (args.saveAuth) {
    await saveAuthInteractive();
    return;
  }

  const env = args.env || 'uat';
  const slots = args.slots?.length ? args.slots : ['Slot015'];

  let langList = args.lang ? [args.lang] : ['bn'];
  if (args.allLangs && args.xlsx) {
    const buf = await fs.readFile(path.resolve(args.xlsx));
    const cfg = await loadConfig();
    langList = (await listLangsFromXlsx(buf))
      .map(l => l.code)
      .filter(code => cfg.langMap?.[code]?.portalLabel);
    if (!langList.length) {
      throw new Error('--all-langs：xlsx 內無可擷取語系（請檢查 langMap.portalLabel）');
    }
    console.log(`語系：${langList.join(', ')}`);
  } else if (!args.lang) {
    langList = ['bn'];
  }

  let xlsxMeta = null;
  if (args.xlsx) {
    const buf = await fs.readFile(path.resolve(args.xlsx));
    for (const slotId of slots) {
      const sheet = args.sheet || slotToSheet(slotId);
      for (const lang of langList) {
        xlsxMeta = await loadKeysFromSheet(buf, sheet, lang);
        console.log(`xlsx 工作表 ${sheet}：${xlsxMeta.keys.length} 個 Key（${lang}）`);
      }
    }
  }

  for (const slotId of slots) {
    const sheetName = args.sheet || slotToSheet(slotId);
    for (const lang of langList) {
      console.log(`\n=== 擷取 ${slotId} / ${lang}（sheet: ${sheetName}）===`);
      await runSlotCapture({
        env,
        lang,
        slotId,
        sheetName,
        onLog: msg => console.log(`  ${msg}`),
      });
    }
  }
}

main().catch(err => {
  console.error(err);
  process.exit(1);
});
