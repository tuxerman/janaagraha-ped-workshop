const tbody = document.getElementById('tenders-body');
const summary = document.getElementById('summary');
const searchInput = document.getElementById('search');
const wardFilter = document.getElementById('ward-filter');
const statusFilter = document.getElementById('status-filter');
const mapLegend = document.getElementById('map-legend');

const STATUS_COLORS = {
  Open: '#0d47a1',
  Awarded: '#4527a0',
  'In Progress': '#e65100',
  Completed: '#1b5e20',
  Cancelled: '#880e4f',
};

const WARD_PALETTE = ['#1565c0', '#6a1b9a', '#00838f', '#ef6c00', '#2e7d32', '#ad1457', '#4527a0', '#00695c'];

const currency = new Intl.NumberFormat('en-IN', {
  style: 'currency',
  currency: 'INR',
  maximumFractionDigits: 0,
});

let allTenders = [];
let leafletMap = null;
let markerLayer = null;

function statusClass(status) {
  return 'status-' + status.toLowerCase().replace(/\s+/g, '-');
}

function wardColor(ward, wards) {
  return WARD_PALETTE[wards.indexOf(ward) % WARD_PALETTE.length];
}

function statusIcon(status) {
  const color = STATUS_COLORS[status] || '#888';
  return L.divIcon({
    className: 'status-pin',
    html: `<span style="background:${color}"></span>`,
    iconSize: [16, 16],
    iconAnchor: [8, 8],
  });
}

function initMap(tenders) {
  leafletMap = L.map('map', {
    scrollWheelZoom: false,
    dragging: !L.Browser.mobile,
  });
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  }).addTo(leafletMap);

  markerLayer = L.layerGroup().addTo(leafletMap);

  const bounds = L.latLngBounds(tenders.map((t) => [t.lat, t.lng]));
  leafletMap.fitBounds(bounds, { padding: [30, 30] });
}

function renderMap(tenders) {
  markerLayer.clearLayers();

  tenders.forEach((t) => {
    const marker = L.marker([t.lat, t.lng], { icon: statusIcon(t.status) });
    marker.bindPopup(
      `<strong>${t.tender_id}</strong><br>${t.title}<br>${t.ward} &middot; ${t.status}<br>${currency.format(t.estimated_amount)}`
    );
    marker.on('click', () => {
      searchInput.value = t.tender_id;
      applyFilters();
      document.getElementById('tenders-table').scrollIntoView({ behavior: 'smooth' });
    });
    marker.addTo(markerLayer);
  });
}

function renderLegend() {
  mapLegend.innerHTML = Object.entries(STATUS_COLORS)
    .map(
      ([status, color]) =>
        `<span class="legend-item"><span class="legend-dot" style="background:${color}"></span>${status}</span>`
    )
    .join('');
}

function renderDonut(svgId, segments) {
  const svg = document.getElementById(svgId);
  const svgNS = 'http://www.w3.org/2000/svg';
  const size = 160;
  const radius = 56;
  const stroke = 26;
  const cx = size / 2;
  const cy = size / 2;
  const circumference = 2 * Math.PI * radius;
  const total = segments.reduce((sum, s) => sum + s.value, 0);

  svg.innerHTML = '';
  svg.setAttribute('viewBox', `0 0 ${size} ${size}`);

  if (total === 0) {
    const empty = document.createElementNS(svgNS, 'circle');
    empty.setAttribute('cx', cx);
    empty.setAttribute('cy', cy);
    empty.setAttribute('r', radius);
    empty.setAttribute('fill', 'none');
    empty.setAttribute('stroke', '#ccc');
    empty.setAttribute('stroke-width', stroke);
    svg.appendChild(empty);
    return;
  }

  let offset = 0;
  segments.forEach((s) => {
    const fraction = s.value / total;
    const dash = fraction * circumference;
    const circle = document.createElementNS(svgNS, 'circle');
    circle.setAttribute('cx', cx);
    circle.setAttribute('cy', cy);
    circle.setAttribute('r', radius);
    circle.setAttribute('fill', 'none');
    circle.setAttribute('stroke', s.color);
    circle.setAttribute('stroke-width', stroke);
    circle.setAttribute('stroke-dasharray', `${dash} ${circumference - dash}`);
    circle.setAttribute('stroke-dashoffset', -offset);
    circle.setAttribute('transform', `rotate(-90 ${cx} ${cy})`);
    svg.appendChild(circle);
    offset += dash;
  });
}

function renderDonutLegend(containerId, items) {
  document.getElementById(containerId).innerHTML = items
    .map(
      (i) =>
        `<span class="legend-item"><span class="legend-dot" style="background:${i.color}"></span>${i.label}</span>`
    )
    .join('');
}

function renderStatusDonut(tenders) {
  const counts = {};
  tenders.forEach((t) => {
    counts[t.status] = (counts[t.status] || 0) + 1;
  });

  const segments = Object.keys(STATUS_COLORS)
    .filter((status) => counts[status])
    .map((status) => ({ label: status, value: counts[status], color: STATUS_COLORS[status] }));

  renderDonut('status-donut', segments);
  renderDonutLegend(
    'status-donut-legend',
    segments.map((s) => ({ label: `${s.label} (${s.value})`, color: s.color }))
  );
}

function renderWardDonut(tenders) {
  const totals = {};
  tenders.forEach((t) => {
    totals[t.ward] = (totals[t.ward] || 0) + t.estimated_amount;
  });

  const wards = Object.keys(totals).sort();
  const segments = wards.map((ward) => ({
    label: ward,
    value: totals[ward],
    color: wardColor(ward, wards),
  }));

  renderDonut('ward-donut', segments);
  renderDonutLegend(
    'ward-donut-legend',
    segments.map((s) => ({ label: `${s.label} (${currency.format(s.value)})`, color: s.color }))
  );
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
  renderStatusDonut(tenders);
  renderWardDonut(tenders);
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
  initMap(allTenders);
  renderLegend();
  populateFilters(allTenders);
  render(allTenders);
}

searchInput.addEventListener('input', applyFilters);
wardFilter.addEventListener('change', applyFilters);
statusFilter.addEventListener('change', applyFilters);

init();
