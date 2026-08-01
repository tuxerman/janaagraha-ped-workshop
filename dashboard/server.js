const http = require('http');
const fs = require('fs');
const path = require('path');

const PORT = process.env.PORT || 3000;
const PUBLIC_DIR = path.join(__dirname, 'public');
const DATA_FILE = path.join(__dirname, 'data', 'tenders.json');
const WORKS_FILE = path.join(__dirname, 'data', 'works.json');

const MIME_TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
};

function loadTenders() {
  return JSON.parse(fs.readFileSync(DATA_FILE, 'utf-8'));
}

function loadWorks() {
  return JSON.parse(fs.readFileSync(WORKS_FILE, 'utf-8'));
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

function serveWorks(req, res, query) {
  const data = loadWorks();
  let works = data.works;

  if (query.ward) {
    works = works.filter((w) => w.ward_name === query.ward);
  }
  if (query.status) {
    works = works.filter((w) => w.status === query.status);
  }
  if (query.q) {
    const needle = query.q.toLowerCase();
    works = works.filter(
      (w) =>
        w.description.toLowerCase().includes(needle) ||
        w.job_number.toLowerCase().includes(needle) ||
        (w.contractor_name || '').toLowerCase().includes(needle)
    );
  }

  res.writeHead(200, { 'Content-Type': MIME_TYPES['.json'] });
  res.end(JSON.stringify({ meta: data._meta, works }));
}

const server = http.createServer((req, res) => {
  const url = new URL(req.url, `http://${req.headers.host}`);

  if (url.pathname === '/api/tenders') {
    serveTenders(req, res, Object.fromEntries(url.searchParams));
    return;
  }

  if (url.pathname === '/api/works') {
    serveWorks(req, res, Object.fromEntries(url.searchParams));
    return;
  }

  serveStatic(req, res, url.pathname);
});

server.listen(PORT, () => {
  console.log(`Civic tenders dashboard running at http://localhost:${PORT}`);
});
