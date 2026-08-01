const tbody = document.getElementById('tenders-body');
const summary = document.getElementById('summary');
const searchInput = document.getElementById('search');
const wardFilter = document.getElementById('ward-filter');
const statusFilter = document.getElementById('status-filter');

const currency = new Intl.NumberFormat('en-IN', {
  style: 'currency',
  currency: 'INR',
  maximumFractionDigits: 0,
});

let allTenders = [];

function statusClass(status) {
  return 'status-' + status.toLowerCase().replace(/\s+/g, '-');
}

function render(tenders) {
  tbody.innerHTML = tenders
    .map(
      (t) => `
    <tr>
      <td>${t.tender_id}</td>
      <td>${t.title}</td>
      <td>${t.ward}</td>
      <td>${t.department}</td>
      <td><span class="status-pill ${statusClass(t.status)}">${t.status}</span></td>
      <td>${currency.format(t.estimated_amount)}</td>
      <td>${t.contractor || '—'}</td>
      <td>${t.closing_date}</td>
    </tr>`
    )
    .join('');

  const total = tenders.reduce((sum, t) => sum + t.estimated_amount, 0);
  summary.textContent = `${tenders.length} tender(s) — total estimated ${currency.format(total)}`;
}

function populateFilters(tenders) {
  const wards = [...new Set(tenders.map((t) => t.ward))].sort();
  const statuses = [...new Set(tenders.map((t) => t.status))].sort();

  wardFilter.innerHTML =
    '<option value="">All wards</option>' +
    wards.map((w) => `<option value="${w}">${w}</option>`).join('');
  statusFilter.innerHTML =
    '<option value="">All statuses</option>' +
    statuses.map((s) => `<option value="${s}">${s}</option>`).join('');
}

function applyFilters() {
  const q = searchInput.value.toLowerCase();
  const ward = wardFilter.value;
  const status = statusFilter.value;

  const filtered = allTenders.filter((t) => {
    if (ward && t.ward !== ward) return false;
    if (status && t.status !== status) return false;
    if (
      q &&
      !(
        t.title.toLowerCase().includes(q) ||
        t.tender_id.toLowerCase().includes(q) ||
        t.location.toLowerCase().includes(q)
      )
    )
      return false;
    return true;
  });

  render(filtered);
}

async function init() {
  const res = await fetch('/api/tenders');
  allTenders = await res.json();
  populateFilters(allTenders);
  render(allTenders);
}

searchInput.addEventListener('input', applyFilters);
wardFilter.addEventListener('change', applyFilters);
statusFilter.addEventListener('change', applyFilters);

init();
