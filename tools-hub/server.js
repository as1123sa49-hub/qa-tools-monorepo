const fs = require('fs');
const path = require('path');
const express = require('express');
const { createProxyMiddleware } = require('http-proxy-middleware');

const app = express();
const PORT = process.env.PORT || 3010;
const IMG_COMPARE_URL = process.env.IMG_COMPARE_URL || 'http://127.0.0.1:3000';
const BONUS_500X_URL = process.env.BONUS_500X_URL || 'http://127.0.0.1:3001';

const hubDir = __dirname;
const toolsRoot = path.join(__dirname, '..', 'tools');
const testCaseGeneratorDir = path.join(toolsRoot, 'test-case-generator');
const frontLogCompareDir = path.join(toolsRoot, 'front-log-compare');
const frontLogCheckerScript = path.join(toolsRoot, 'front-log-checker', 'intercept.js');
const readmeMap = {
  'img-compare': path.join(toolsRoot, 'img-compare', 'README.md'),
  'test-case-generator': path.join(toolsRoot, 'test-case-generator', 'README.md'),
  'bonus-v2': path.join(toolsRoot, 'bonus-v2', 'README.md'),
  'tools-hub': path.join(hubDir, 'README.md'),
  'front-log-checker': path.join(toolsRoot, 'front-log-checker', 'README.md'),
  'front-log-compare': path.join(toolsRoot, 'front-log-compare', 'README.md')
};

app.use(express.static(hubDir));

// test-case-generator is a static tool; mount it directly.
app.use(
  '/apps/test-case-generator',
  express.static(testCaseGeneratorDir)
);

// front-log-compare: static UI + app.js（與獨立 npm start 同源）
app.use('/apps/front-log-compare', express.static(frontLogCompareDir));
app.get('/apps/front-log-compare', (_req, res) => res.redirect('/apps/front-log-compare/'));

// bonus-v2 (500X) has its own server/api; proxy through hub.
app.use(
  '/apps/bonus-v2',
  createProxyMiddleware({
    target: BONUS_500X_URL,
    changeOrigin: true,
    pathRewrite: (path) => path.replace(/^\/apps\/bonus-v2/, '') || '/'
  })
);
app.get('/apps/bonus-v2', (_req, res) => res.redirect('/apps/bonus-v2/'));

// img-compare has its own server/api; proxy through hub.
app.use(
  '/apps/img-compare',
  createProxyMiddleware({
    target: IMG_COMPARE_URL,
    changeOrigin: true,
    pathRewrite: (path) => path.replace(/^\/apps\/img-compare/, '') || '/'
  })
);
app.get('/apps/img-compare', (_req, res) => res.redirect('/apps/img-compare/'));

// bonus-v2 API proxy (hub origin → 3001 /api/*)
app.use(
  '/api/bonus-v2',
  createProxyMiddleware({
    target: BONUS_500X_URL,
    changeOrigin: true,
    pathRewrite: (path) => `/api${path}`
  })
);

app.get('/api/docs/:tool', (req, res) => {
  const tool = req.params.tool;
  const readmePath = readmeMap[tool];

  if (!readmePath) {
    return res.status(404).json({ error: 'unknown tool' });
  }

  if (!fs.existsSync(readmePath)) {
    return res.status(404).json({ error: 'readme not found' });
  }

  try {
    const markdown = fs.readFileSync(readmePath, 'utf8');
    return res.json({ tool, markdown });
  } catch (_err) {
    return res.status(500).json({ error: 'failed to load readme' });
  }
});

app.use(
  '/api',
  createProxyMiddleware({
    target: IMG_COMPARE_URL,
    changeOrigin: true,
    pathRewrite: (path) => `/api${path}`
  })
);

app.get('/snippets/front-log-checker.txt', (_req, res) => {
  res.type('text/plain; charset=utf-8');
  res.sendFile(frontLogCheckerScript);
});

app.get('/', (_req, res) => {
  res.sendFile(path.join(hubDir, 'index.html'));
});

app.listen(PORT, () => {
  console.log('QA Tools Hub started');
  console.log(`Hub URL: http://localhost:${PORT}`);
  console.log(`img-compare target: ${IMG_COMPARE_URL}`);
  console.log(`bonus-v2 (500X) target: ${BONUS_500X_URL}`);
});
