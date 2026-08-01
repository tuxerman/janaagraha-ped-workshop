const tbody = document.getElementById('tenders-body');
const summary = document.getElementById('summary');
const searchInput = document.getElementById('search');
const wardFilter = document.getElementById('ward-filter');
const statusFilter = document.getElementById('status-filter');
const map = document.getElementById('map');
const mapLegend = document.getElementById('map-legend');

const STATUS_COLORS = {
  Open: '#0d47a1',
  Awarded: '#4527a0',
  'In Progress': '#e65100',
  Completed: '#1b5e20',
  Cancelled: '#880e4f',
};

const MAP_PADDING = 40;

const currency = new Intl.NumberFormat('en-IN', {
  style: 'currency',
  currency: 'INR',
  maximumFractionDigits: 0,
});

let allTenders = [];
let mapBounds = null;

function statusClass(status) {
  return 'status-' + status.toLowerCase().replace(/\s+/g, '-');
}

function computeMapBounds(tenders) {
  const lats = tenders.map((t) => t.lat);
  const lngs = tenders.map((t) => t.lng);
  return {
    minLat: Math.min(...lats),
    maxLat: Math.max(...lats),
    minLng: Math.min(...lngs),
    maxLng: Math.max(...lngs),
  };
}

function project(t) {
  const { minLat, maxLat, minLng, maxLng } = mapBounds;
  const w = map.viewBox.baseVal.width - MAP_PADDING * 2;
  const h = map.viewBox.baseVal.height - MAP_PADDING * 2;
  const x = MAP_PADDING + ((t.lng - minLng) / (maxLng - minLng || 1)) * w;
  const y = MAP_PADDING + (1 - (t.lat - minLat) / (maxLat - minLat || 1)) * h;
  return { x, y };
}

function renderLegend() {
  mapLegend.innerHTML = Object.entries(STATUS_COLORS)
    .map(
      ([status, color]) =>
        `<span class="legend-item"><span class="legend-dot" style="background:${color}"></span>${status}</span>`
    )
    .join('');
}

function renderMap(tenders) {
  const svgNS = 'http://www.w3.org/2000/svg';
  map.innerHTML = '';

  const background = document.createElementNS(svgNS, 'rect');
  background.setAttribute('x', '0');
  background.setAttribute('y', '0');
  background.setAttribute('width', map.viewBox.baseVal.width);
  background.setAttribute('height', map.viewBox.baseVal.height);
  background.setAttribute('class', 'map-background');
  map.appendChild(background);

  tenders.forEach((t) => {
    const { x, y } = project(t);
    const circle = document.createElementNS(svgNS, 'circle');
    circle.setAttribute('cx', x);
    circle.setAttribute('cy', y);
    circle.setAttribute('r', 7);
    circle.setAttribute('fill', STATUS_COLORS[t.status] || '#888');
    circle.setAttribute('class', 'map-pin');
    circle.addEventListener('click', () => {
      searchInput.value = t.tender_id;
      applyFilters();
      document.getElementById('tenders-table').scrollIntoView({ behavior: 'smooth' });
    });

    const title = document.createElementNS(svgNS, 'title');
    title.textContent = `${t.tender_id} — ${t.title}\n${t.ward} · ${t.status} · ${currency.format(t.estimated_amount)}`;
    circle.appendChild(title);

    map.appendChild(circle);
  });
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
    </tr>`
    )
    .join('');

  const total = tenders.reduce((sum, t) => sum + t.estimated_amount, 0);
  summary.textContent = `${tenders.length} tender(s) — total estimated ${currency.format(total)}`;

  renderMap(tenders);
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
  mapBounds = computeMapBounds(allTenders);
  renderLegend();
  populateFilters(allTenders);
  render(allTenders);
}

searchInput.addEventListener('input', applyFilters);
wardFilter.addEventListener('change', applyFilters);
statusFilter.addEventListener('change', applyFilters);

init();
