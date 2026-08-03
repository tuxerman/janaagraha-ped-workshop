const http = require('http');
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

const PORT = process.env.PORT || 3000;
const PUBLIC_DIR = path.join(__dirname, 'public');
const MANIFEST_FILE = path.join(__dirname, '..', 'data_backend', 'json', 'works.manifest.json');
const WORKS_DIR = path.join(__dirname, '..', 'data_backend', 'json', 'works');

const MIME_TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
};

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, 'utf-8'));
}

function loadDataset() {
  const manifest = readJson(MANIFEST_FILE);
  if (!Array.isArray(manifest.chunks) || manifest.chunks.length === 0) {
    throw new Error(`${MANIFEST_FILE} does not list any chunks`);
  }
  const works = [];
  manifest.chunks.forEach((chunk) => {
    const chunkPath = path.resolve(path.dirname(MANIFEST_FILE), chunk.file);
    if (!chunkPath.startsWith(`${WORKS_DIR}${path.sep}`)) {
      throw new Error(`Chunk path escapes the works directory: ${chunk.file}`);
    }
    const content = fs.readFileSync(chunkPath);
    const digest = crypto.createHash('sha256').update(content).digest('hex');
    if (content.length !== chunk.bytes || digest !== chunk.sha256) {
      throw new Error(`Chunk checksum or size mismatch: ${chunkPath}`);
    }
    const records = JSON.parse(content.toString('utf-8'));
    if (!Array.isArray(records) || records.length !== chunk.records) {
      throw new Error(`Chunk record count mismatch: ${chunkPath}`);
    }
    works.push(...records);
  });
  if (works.length !== manifest.record_count) {
    throw new Error(
      `Work chunks have ${works.length} records; manifest expects ${manifest.record_count}`
    );
  }
  return { works, manifest };
}

// Flattened for the browser: one entry per PDF-extracted road stretch, carrying
// just enough of data_schema.md's `road_segments[]` block (method/confidence,
// per the project's linking rules) to draw the line and label it honestly —
// not the full notes/source-document trail.
function summarizeRoadSegments(work) {
  if (!Array.isArray(work.road_segments)) return [];
  return work.road_segments.flatMap((block) =>
    (block.segments || [])
      .filter((segment) => segment.start && segment.end)
      .map((segment) => ({
        segment_number: segment.segment_number,
        length_m: segment.length_m,
        start: segment.start,
        end: segment.end,
        confidence: block.extraction_confidence,
        source_document: block.source_document,
      }))
  );
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
    road_segments: summarizeRoadSegments(work),
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
