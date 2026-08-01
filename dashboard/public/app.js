const tbody = document.getElementById('works-body');
const summary = document.getElementById('summary');
const searchInput = document.getElementById('search');
const wardFilter = document.getElementById('ward-filter');
const statusFilter = document.getElementById('status-filter');
const mapElement = document.getElementById('map');
const mapLegend = document.getElementById('map-legend');
const dataBanner = document.getElementById('data-banner');

const STATUS_COLORS = {
  completed: '#1b5e20',
  in_progress: '#e65100',
  unknown: '#616161',
};
const WARD_PALETTE = [
  '#1565c0',
  '#6a1b9a',
  '#00838f',
  '#ef6c00',
  '#2e7d32',
  '#ad1457',
  '#4527a0',
  '#00695c',
];
const MAX_TABLE_ROWS = 500;
const UNKNOWN_WARD = 'Centralised / unknown';

const currency = new Intl.NumberFormat('en-IN', {
  style: 'currency',
  currency: 'INR',
  maximumFractionDigits: 0,
});

let allWorks = [];
let leafletMap = null;
let markerLayer = null;

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function statusLabel(status) {
  return status
    .split('_')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
}

function wardLabel(work) {
  return work.ward_name || UNKNOWN_WARD;
}

function hasPoint(work) {
  return Number.isFinite(work.lat) && Number.isFinite(work.lng);
}

function statusIcon(status) {
  const color = STATUS_COLORS[status] || STATUS_COLORS.unknown;
  return L.divIcon({
    className: 'status-pin',
    html: `<span style="background:${color}"></span>`,
    iconSize: [16, 16],
    iconAnchor: [8, 8],
  });
}

function initMap(works) {
  const locatedWorks = works.filter(hasPoint);
  if (locatedWorks.length === 0) {
    mapElement.classList.add('map-empty');
    mapElement.textContent =
      'No point coordinates are available in the current source data. Ward-level location labels are shown in the table.';
    mapLegend.textContent = '0 works with point coordinates';
    return;
  }

  leafletMap = L.map('map', {
    scrollWheelZoom: false,
    dragging: !L.Browser.mobile,
  });
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; OpenStreetMap contributors',
  }).addTo(leafletMap);
  markerLayer = L.layerGroup().addTo(leafletMap);
  const bounds = L.latLngBounds(locatedWorks.map((work) => [work.lat, work.lng]));
  leafletMap.fitBounds(bounds, { padding: [30, 30] });
  renderLegend();
}

function renderMap(works) {
  if (!markerLayer) return;
  markerLayer.clearLayers();

  works.filter(hasPoint).forEach((work) => {
    const marker = L.marker([work.lat, work.lng], { icon: statusIcon(work.status) });
    marker.bindPopup(
      `<strong>${escapeHtml(work.job_number)}</strong><br>${escapeHtml(work.description)}<br>${escapeHtml(wardLabel(work))} &middot; ${escapeHtml(statusLabel(work.status))}<br>${currency.format(work.amount_gross)}`
    );
    marker.on('click', () => {
      searchInput.value = work.job_number;
      applyFilters();
      document.getElementById('works-table').scrollIntoView({ behavior: 'smooth' });
    });
    marker.addTo(markerLayer);
  });
}

function renderLegend() {
  mapLegend.innerHTML = Object.entries(STATUS_COLORS)
    .map(
      ([status, color]) =>
        `<span class="legend-item"><span class="legend-dot" style="background:${color}"></span>${statusLabel(status)}</span>`
    )
    .join('');
}

function renderDonut(svgId, segments) {
  const svg = document.getElementById(svgId);
  const svgNS = 'http://www.w3.org/2000/svg';
  const size = 160;
  const radius = 56;
  const stroke = 26;
  const center = size / 2;
  const circumference = 2 * Math.PI * radius;
  const total = segments.reduce((sum, segment) => sum + segment.value, 0);

  svg.innerHTML = '';
  svg.setAttribute('viewBox', `0 0 ${size} ${size}`);
  if (total === 0) return;

  let offset = 0;
  segments.forEach((segment) => {
    const dash = (segment.value / total) * circumference;
    const circle = document.createElementNS(svgNS, 'circle');
    circle.setAttribute('cx', center);
    circle.setAttribute('cy', center);
    circle.setAttribute('r', radius);
    circle.setAttribute('fill', 'none');
    circle.setAttribute('stroke', segment.color);
    circle.setAttribute('stroke-width', stroke);
    circle.setAttribute('stroke-dasharray', `${dash} ${circumference - dash}`);
    circle.setAttribute('stroke-dashoffset', -offset);
    circle.setAttribute('transform', `rotate(-90 ${center} ${center})`);
    svg.appendChild(circle);
    offset += dash;
  });
}

function renderDonutLegend(containerId, items) {
  document.getElementById(containerId).innerHTML = items
    .map(
      (item) =>
        `<span class="legend-item"><span class="legend-dot" style="background:${item.color}"></span>${escapeHtml(item.label)}</span>`
    )
    .join('');
}

function renderStatusDonut(works) {
  const counts = {};
  works.forEach((work) => {
    counts[work.status] = (counts[work.status] || 0) + 1;
  });
  const segments = Object.keys(STATUS_COLORS)
    .filter((status) => counts[status])
    .map((status) => ({
      label: statusLabel(status),
      value: counts[status],
      color: STATUS_COLORS[status],
    }));
  renderDonut('status-donut', segments);
  renderDonutLegend(
    'status-donut-legend',
    segments.map((segment) => ({
      label: `${segment.label} (${segment.value.toLocaleString('en-IN')})`,
      color: segment.color,
    }))
  );
}

function renderWardDonut(works) {
  const totals = {};
  works.forEach((work) => {
    const ward = wardLabel(work);
    totals[ward] = (totals[ward] || 0) + work.amount_gross;
  });
  const ranked = Object.entries(totals).sort((left, right) => right[1] - left[1]);
  const top = ranked.slice(0, 7);
  const other = ranked.slice(7).reduce((sum, [, amount]) => sum + amount, 0);
  if (other > 0) top.push(['Other wards', other]);
  const segments = top.map(([ward, amount], index) => ({
    label: ward,
    value: amount,
    color: WARD_PALETTE[index % WARD_PALETTE.length],
  }));
  renderDonut('ward-donut', segments);
  renderDonutLegend(
    'ward-donut-legend',
    segments.map((segment) => ({
      label: `${segment.label} (${currency.format(segment.value)})`,
      color: segment.color,
    }))
  );
}

function render(works) {
  const visible = works.slice(0, MAX_TABLE_ROWS);
  tbody.innerHTML = visible
    .map(
      (work) => `
    <tr>
      <td>${escapeHtml(work.job_number)}</td>
      <td>${escapeHtml(work.description)}</td>
      <td>${escapeHtml(wardLabel(work))}</td>
      <td>${escapeHtml(work.zone || '—')}</td>
      <td><span class="status-pill status-${escapeHtml(work.status.replaceAll('_', '-'))}">${escapeHtml(statusLabel(work.status))}</span></td>
      <td>${currency.format(work.amount_gross)}</td>
      <td>${work.bill_count.toLocaleString('en-IN')}</td>
      <td>${escapeHtml(work.contractor_name || '—')}</td>
    </tr>`
    )
    .join('');

  const total = works.reduce((sum, work) => sum + work.amount_gross, 0);
  const tableNote =
    works.length > MAX_TABLE_ROWS ? ` Showing the first ${MAX_TABLE_ROWS.toLocaleString('en-IN')}.` : '';
  summary.textContent = `${works.length.toLocaleString('en-IN')} work(s) — gross paid ${currency.format(total)}.${tableNote}`;
  renderMap(works);
  renderStatusDonut(works);
  renderWardDonut(works);
}

function populateFilters(works) {
  const wards = [...new Set(works.map(wardLabel))].sort();
  const statuses = [...new Set(works.map((work) => work.status))].sort();
  wardFilter.innerHTML =
    '<option value="">All wards</option>' +
    wards.map((ward) => `<option value="${escapeHtml(ward)}">${escapeHtml(ward)}</option>`).join('');
  statusFilter.innerHTML =
    '<option value="">All statuses</option>' +
    statuses
      .map(
        (status) =>
          `<option value="${escapeHtml(status)}">${escapeHtml(statusLabel(status))}</option>`
      )
      .join('');
}

function applyFilters() {
  const needle = searchInput.value.trim().toLowerCase();
  const ward = wardFilter.value;
  const status = statusFilter.value;
  const filtered = allWorks.filter((work) => {
    if (ward && wardLabel(work) !== ward) return false;
    if (status && work.status !== status) return false;
    if (!needle) return true;
    return [
      work.job_number,
      work.description,
      work.contractor_name,
      wardLabel(work),
      work.zone || '',
    ].some((value) => String(value).toLowerCase().includes(needle));
  });
  render(filtered);
}

async function init() {
  try {
    const response = await fetch('/api/works');
    if (!response.ok) throw new Error(`API returned ${response.status}`);
    const payload = await response.json();
    allWorks = payload.works;
    dataBanner.textContent =
      `Source data through ${payload.meta.as_of_date}: ${payload.meta.record_count.toLocaleString('en-IN')} works. Tender links and exact coordinates remain unavailable where the source cannot support them.`;
    initMap(allWorks);
    populateFilters(allWorks);
    render(allWorks);
  } catch (error) {
    dataBanner.textContent = `Could not load works data: ${error.message}`;
    dataBanner.classList.add('data-banner-error');
  }
}

searchInput.addEventListener('input', applyFilters);
wardFilter.addEventListener('change', applyFilters);
statusFilter.addEventListener('change', applyFilters);

init();
