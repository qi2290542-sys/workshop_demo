/**
 * 阀门维护 Window-UI 本地服务
 *
 * 启动：node server.js
 * 端口：3401
 *
 * 作用：托管 window-ui.html，供 main.js 中 WindowUI 以 iframe 方式加载。
 * 确保 main.js 中 windowUiPort 与本服务端口一致。
 */

const http = require('http');
const fs = require('fs');
const path = require('path');
const os = require('os');

const PORT = 3401;

function getLocalIP() {
  const interfaces = os.networkInterfaces();
  for (const name of Object.keys(interfaces)) {
    for (const iface of interfaces[name]) {
      if (iface.family === 'IPv4' && !iface.internal) return iface.address;
    }
  }
  return 'localhost';
}

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.css':  'text/css; charset=utf-8',
  '.js':   'application/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.png':  'image/png',
  '.ico':  'image/x-icon',
};

const server = http.createServer((req, res) => {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') {
    res.writeHead(204);
    res.end();
    return;
  }

  let urlPath = req.url.split('?')[0];
  if (urlPath === '/' || urlPath === '/index.html') {
    urlPath = '/window-ui.html';
  }

  const filePath = path.join(__dirname, urlPath);

  // 防止目录穿越
  if (!filePath.startsWith(__dirname)) {
    res.writeHead(403);
    res.end('Forbidden');
    return;
  }

  fs.readFile(filePath, (err, data) => {
    if (err) {
      res.writeHead(404, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: 'Not found', path: urlPath }));
      return;
    }
    const ext = path.extname(filePath);
    const contentType = MIME[ext] || 'application/octet-stream';
    res.writeHead(200, { 'Content-Type': contentType });
    res.end(data);
  });
});

server.listen(PORT, '0.0.0.0', () => {
  const ip = getLocalIP();
  console.log(`阀门维护 UI 服务已启动`);
  console.log(`  本机访问：http://localhost:${PORT}/`);
  console.log(`  局域网：  http://${ip}:${PORT}/`);
  console.log('');
  console.log('确保 main.js 中 windowUiPort =', PORT);
});
