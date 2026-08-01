const http = require('http');
const fs = require('fs');
const path = require('path');

const PORT = process.env.PORT || 3000;
const PUBLIC_DIR = path.join(__dirname, 'public');
const WORKS_FILE = path.join(__dirname, '..', 'data_backend', 'json', 'works.json');
const MANIFEST_FILE = path.join(__dirname, '..', 'data_backend', 'json', 'works.manifest.json');

const MIME_TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
};

function readJson(filePath) {
  const content = fs.readFileSync(filePath, 'utf-8');
  if (content.startsWith('version https://git-lfs.github.com/spec/')) {
    throw new Error(`${filePath} is a Git LFS pointer. Run "git lfs pull" first.`);
  }
  return JSON.parse(content);
}

function loadDataset() {
  const works = readJson(WORKS_FILE);
  const manifest = readJson(MANIFEST_FILE);
  if (!Array.isArray(works)) {
    throw new Error(`${WORKS_FILE} must contain a JSON array`);
  }
  if (works.length !== manifest.record_count) {
    throw new Error(
      `works.json has ${works.length} records; manifest expects ${manifest.record_count}`
    );
  }
  return { works, manifest };
}

function summarizeWork(work) {
  const location = work.location || {};
  return {
    job_number: work.job_number,
    description: work.description,
    ward_number: work.ward_number,
    ward_name: work.ward_name,
    ward_scheme: work.ward_scheme,
    zone: work.zone,
    award_fy: work.award_fy,
    contractor_name: work.contractor_name,
    amount_gross: work.amount_gross,
    amount_net: work.amount_net,
    amount_deduction: work.amount_deduction,
    estimated_amount: work.estimated_amount,
    bill_count: work.bill_count,
    first_bill_date: work.first_bill_date,
    last_bill_date: work.last_bill_date,
    status: work.status,
    tender_linked: work.tender !== null,
    link_failure_reason: work.link_failure_reason || null,
    document_count: Array.isArray(work.documents) ? work.documents.length : 0,
    location_precision: location.precision || 'none',
    lat: Number.isFinite(location.lat) ? location.lat : null,
    lng: Number.isFinite(location.lng) ? location.lng : null,
  };
}

function filterWorks(works, query) {
  const ward = query.ward || '';
  const status = query.status || '';
  const needle = (query.q || '').trim().toLowerCase();

  return works.filter((work) => {
    const workWard = work.ward_name || '';
    if (ward && workWard !== ward) return false;
    if (status && work.status !== status) return false;
    if (!needle) return true;
    return [
      work.job_number,
      work.description,
      work.contractor_name,
      workWard,
      work.zone || '',
    ].some((value) => String(value).toLowerCase().includes(needle));
  });
}

function serveStatic(req, res, pathname) {
  const relPath = pathname === '/' ? 'index.html' : pathname.replace(/^\/+/, '');
  const filePath = path.resolve(PUBLIC_DIR, relPath);

  if (filePath !== PUBLIC_DIR && !filePath.startsWith(`${PUBLIC_DIR}${path.sep}`)) {
    res.writeHead(403);
    res.end('Forbidden');
    return;
  }

  fs.readFile(filePath, (error, content) => {
    if (error) {
      res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
      res.end('Not found');
      return;
    }
    const ext = path.extname(filePath);
    res.writeHead(200, { 'Content-Type': MIME_TYPES[ext] || 'application/octet-stream' });
    res.end(content);
  });
}

function createServer(dataset = loadDataset()) {
  const works = dataset.works.map(summarizeWork);
  const meta = {
    schema_version: dataset.manifest.schema_version,
    as_of_date: dataset.manifest.as_of_date,
    record_count: dataset.manifest.record_count,
    stats: dataset.manifest.stats,
  };
  const unfilteredPayload = JSON.stringify({ meta, works });

  return http.createServer((req, res) => {
    const url = new URL(req.url, `http://${req.headers.host || 'localhost'}`);

    if (url.pathname === '/api/works') {
      const query = Object.fromEntries(url.searchParams);
      const hasFilters = Boolean(query.ward || query.status || query.q);
      const payload = hasFilters
        ? JSON.stringify({ meta, works: filterWorks(works, query) })
        : unfilteredPayload;
      res.writeHead(200, { 'Content-Type': MIME_TYPES['.json'] });
      res.end(payload);
      return;
    }

    serveStatic(req, res, url.pathname);
  });
}

if (require.main === module) {
  const server = createServer();
  server.listen(PORT, () => {
    console.log(`Civic works dashboard running at http://localhost:${PORT}`);
  });
}

module.exports = { createServer, filterWorks, loadDataset, summarizeWork };
