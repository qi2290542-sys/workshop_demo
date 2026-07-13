/**
 * 极简本地 HTTP 服务，将 sluice.exe 包装为 HTTP 接口
 * 启动：node server.js
 * 端口：9527（可按需修改）
 */
const http = require('http');
const { execFile } = require('child_process');
const path = require('path');
const fs = require('fs');

// 静态文件目录：D:\huangqi\workshop\public\
const PUBLIC_DIR = path.resolve(__dirname, '..', '..', '..', 'public');

const MIME_TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.js':   'application/javascript; charset=utf-8',
  '.css':  'text/css; charset=utf-8',
  '.png':  'image/png',
  '.jpg':  'image/jpeg',
  '.svg':  'image/svg+xml',
  '.ico':  'image/x-icon',
};

function serveStatic(req, res) {
  const urlPath = req.url.split('?')[0];
  const filePath = path.resolve(PUBLIC_DIR, '.' + urlPath);
  // 防止路径穿越
  if (!filePath.startsWith(PUBLIC_DIR)) {
    res.writeHead(403);
    return res.end('Forbidden');
  }
  fs.readFile(filePath, (err, data) => {
    if (err) {
      res.writeHead(404);
      return res.end('Not Found');
    }
    const ext = path.extname(filePath).toLowerCase();
    res.setHeader('Content-Type', MIME_TYPES[ext] || 'application/octet-stream');
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.writeHead(200);
    res.end(data);
  });
}

const PORT = 9527;
const SLUICE_PATH = path.join(__dirname, 'sluice.exe');

function buildForwardArgs(body) {
  return [
    'forward', '--json',
    '--num-gates',           String(body.num_gates ?? 5),
    '--gate-width',          String(body.gate_width ?? 5),
    '--openings',            (body.openings ?? []).join(','),
    '--upstream-level',      String(body.upstream_level),
    '--downstream-level',    String(body.downstream_level),
    '--gate-bottom-elevation', String(body.gate_bottom_elevation ?? 0),
  ];
}

function buildOptimizeArgs(body) {
  return [
    'optimize', '--json',
    '--target-discharge',    String(body.target_discharge),
    '--num-gates',           String(body.num_gates ?? 5),
    '--gate-width',          String(body.gate_width ?? 5),
    '--max-opening',         String(body.max_opening ?? 3),
    '--min-opening',         String(body.min_opening ?? 0.2),
    '--upstream-level',      String(body.upstream_level),
    '--downstream-level',    String(body.downstream_level),
    '--gate-bottom-elevation', String(body.gate_bottom_elevation ?? 0),
  ];
}

function runCli(args) {
  return new Promise((resolve, reject) => {
    execFile(SLUICE_PATH, args, { timeout: 30000 }, (err, stdout, stderr) => {
      if (err) {
        if (stdout?.trim()) {
          try { return resolve(JSON.parse(stdout.trim())); } catch (_) {}
        }
        return reject(new Error(stderr || err.message));
      }
      try {
        resolve(JSON.parse(stdout.trim()));
      } catch (_) {
        reject(new Error('CLI returned invalid JSON: ' + stdout));
      }
    });
  });
}

const server = http.createServer((req, res) => {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') {
    res.writeHead(204);
    return res.end();
  }

  const isForward  = req.method === 'POST' && req.url === '/api/sluice/forward';
  const isOptimize = req.method === 'POST' && req.url === '/api/sluice/optimize';

  if (!isForward && !isOptimize) {
    if (req.method === 'GET') {
      return serveStatic(req, res);
    }
    res.writeHead(404);
    return res.end(JSON.stringify({ error: 'Not Found' }));
  }

  res.setHeader('Content-Type', 'application/json');
  let rawBody = '';
  req.on('data', chunk => rawBody += chunk);
  req.on('end', async () => {
    try {
      const body = JSON.parse(rawBody);
      const args = isForward ? buildForwardArgs(body) : buildOptimizeArgs(body);
      const result = await runCli(args);
      res.writeHead(200);
      res.end(JSON.stringify(result));
    } catch (e) {
      res.writeHead(500);
      res.end(JSON.stringify({ success: false, error: e.message }));
    }
  });
});

server.listen(PORT, '127.0.0.1', () => {
  console.log(`✅ sluice 本地服务已启动：http://127.0.0.1:${PORT}`);
  console.log(`   POST http://127.0.0.1:${PORT}/api/sluice/forward`);
  console.log(`   POST http://127.0.0.1:${PORT}/api/sluice/optimize`);
});
