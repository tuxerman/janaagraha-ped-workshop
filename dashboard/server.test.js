const assert = require('node:assert/strict');
const test = require('node:test');

const { createServer, filterWorks, loadDataset, summarizeWork } = require('./server');

const fixture = {
  job_number: '087-21-000011',
  description: 'Providing Tractor and Gangmen in Ward No. 87 HAL Airport',
  ward_number: 87,
  ward_name: 'HAL Airport',
  ward_scheme: '198',
  zone: 'Mahadevapura',
  award_fy: '2021-22',
  contractor_name: 'Example Contractors',
  amount_gross: 1561836,
  amount_net: 1405652,
  amount_deduction: 156184,
  estimated_amount: null,
  bill_count: 1,
  first_bill_date: '2024-06-11',
  last_bill_date: '2024-06-11',
  status: 'completed',
  tender: null,
  link_failure_reason: 'no_candidate_found',
  location: { lat: null, lng: null, precision: 'ward' },
  documents: [{ doc_type: 'Work Order' }],
  bills: [{ bill_type: 'Final' }],
};

test('summarizeWork returns dashboard fields without heavy nested arrays', () => {
  const summary = summarizeWork(fixture);
  assert.equal(summary.job_number, fixture.job_number);
  assert.equal(summary.document_count, 1);
  assert.equal(summary.location_precision, 'ward');
  assert.equal(summary.lat, null);
  assert.equal('documents' in summary, false);
  assert.equal('bills' in summary, false);
});

test('filterWorks searches work fields and respects exact filters', () => {
  const works = [summarizeWork(fixture)];
  assert.equal(filterWorks(works, { q: 'tractor' }).length, 1);
  assert.equal(filterWorks(works, { ward: 'HAL Airport', status: 'completed' }).length, 1);
  assert.equal(filterWorks(works, { status: 'unknown' }).length, 0);
});

test('loadDataset reads the generated pipeline output', () => {
  const dataset = loadDataset();
  assert.equal(dataset.works.length, dataset.manifest.record_count);
  assert.ok(dataset.works.length > 8000);
});

test('/api/works serves summaries and metadata', async (context) => {
  const dataset = {
    works: [fixture],
    manifest: {
      schema_version: '0.1',
      as_of_date: '2026-07-30',
      record_count: 1,
      stats: {},
    },
  };
  const server = createServer(dataset);
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  context.after(() => server.close());
  const { port } = server.address();
  const response = await fetch(`http://127.0.0.1:${port}/api/works`);
  const payload = await response.json();

  assert.equal(response.status, 200);
  assert.equal(payload.meta.record_count, 1);
  assert.equal(payload.works[0].job_number, fixture.job_number);
  assert.equal('documents' in payload.works[0], false);
});
