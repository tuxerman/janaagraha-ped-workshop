const http = require('http');
const fs = require('fs');
const path = require('path');

const PORT = process.env.PORT || 3000;
const PUBLIC_DIR = path.join(__dirname, 'public');
const DATA_FILE = path.join(__dirname, 'data', 'tenders.json');

const MIME_TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
};

function loadTenders() {
  return JSON.parse(fs.readFileSync(DATA_FILE, 'utf-8'));
}

function serveStatic(req, res, pathname) {
  const relPath = pathname === '/' ? '/index.html' : pathname;
  const filePath = path.join(PUBLIC_DIR, path.normalize(relPath));

  if (!filePath.startsWith(PUBLIC_DIR)) {
    res.writeHead(403);
    res.end('Forbidden');
    return;
  }

  fs.readFile(filePath, (err, content) => {
    if (err) {
      res.writeHead(404, { 'Content-Type': 'text/plain' });
      res.end('Not found');
      return;
    }
    const ext = path.extname(filePath);
    res.writeHead(200, { 'Content-Type': MIME_TYPES[ext] || 'application/octet-stream' });
    res.end(content);
  });
}

function serveTenders(req, res, query) {
  let tenders = loadTenders();

  if (query.ward) {
    tenders = tenders.filter((t) => t.ward === query.ward);
  }
  if (query.status) {
    tenders = tenders.filter((t) => t.status === query.status);
  }
  if (query.q) {
    const needle = query.q.toLowerCase();
    tenders = tenders.filter(
      (t) =>
        t.title.toLowerCase().includes(needle) ||
        t.tender_id.toLowerCase().includes(needle) ||
        t.location.toLowerCase().includes(needle)
    );
  }

  res.writeHead(200, { 'Content-Type': MIME_TYPES['.json'] });
  res.end(JSON.stringify(tenders));
}

const server = http.createServer((req, res) => {
  const url = new URL(req.url, `http://${req.headers.host}`);

  if (url.pathname === '/api/tenders') {
    serveTenders(req, res, Object.fromEntries(url.searchParams));
    return;
  }

  serveStatic(req, res, url.pathname);
});

server.listen(PORT, () => {
  console.log(`Civic tenders dashboard running at http://localhost:${PORT}`);
});
