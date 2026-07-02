/**
 * 向後相容入口：對外維持從 capture-flow.js import 的習慣。
 */
export { loadConfig, outputDir } from './config.js';
export { CAPTURE_META_FILE } from './capture-meta.js';
export { runSlotCapture, saveAuthInteractive } from './run-slot-capture.js';
