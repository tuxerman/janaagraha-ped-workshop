const tbody = document.getElementById('works-body');
const summary = document.getElementById('summary');
const searchInput = document.getElementById('search');
const wardFilter = document.getElementById('ward-filter');
const statusFilter = document.getElementById('status-filter');
const categoryFilter = document.getElementById('category-filter');
const categoryRulesList = document.getElementById('category-rules-list');
const categoryTotalsBody = document.getElementById('category-totals-body');
const mapElement = document.getElementById('map');
const mapLegend = document.getElementById('map-legend');
const dataBanner = document.getElementById('data-banner');

const STATUS_COLORS = {
  completed: '#1b5e20',
  in_progress: '#e65100',
  unknown: '#616161',
};

// Ordered, first-match-wins keyword brackets used to tag each work's description.
// A rough automatic sort, not a verified classification — see the "How are categories
// assigned?" note in the UI. Anything matching none of these lands in Unassigned & Others.
const CATEGORIES = [
  {
    key: 'health',
    label: 'Health',
    color: '#c62828',
    keywords: ['hospital', 'hosp', 'dispensary', 'phc', 'clinic', 'ayush', 'ambulance', 'medical'],
  },
  {
    key: 'education',
    label: 'Education',
    color: '#f9a825',
    keywords: ['school', 'college', 'vidyalaya', 'anganwadi', 'student', 'books', 'book', 'shoe', 'sock', 'uniform'],
  },
  {
    key: 'environment',
    label: 'Environment',
    color: '#2e7d32',
    keywords: ['lake', 'kere', 'kalyani', 'pond', 'wetland', 'plantation', 'rainwater harvesting', 'tree', 'garden', 'dobhighat', 'biodiversity'],
  },
  {
    key: 'mobility',
    label: 'Physical Mobility Infrastructure',
    color: '#1565c0',
    keywords: ['road', 'footpath', 'foot path', 'pavement', 'asphalt', 'resurfac', 'storm water drain', 'swd', 'drain', 'culvert', 'bridge', 'kerb', 'underpass', 'flyover', 'junction', 'widening', 'pothole', 'pot hole', 'pathway', 'cross road', 'carpet', 'wmm', 'median', 'boulevard'],
  },
  {
    key: 'amenities',
    label: 'Public Amenities & Parks',
    color: '#6a1b9a',
    keywords: ['toilet', 'park', 'playground', 'auditorium', 'kalyana mantapa', 'community hall', 'samudaya bhavana', 'bhavana', 'hall', 'yoga', 'gym', 'compound wall', 'burial ground', 'crematorium', 'market', 'bus shelter', 'street light', 'streetlight', 'led light', 'bench', 'borewell', 'water tank', 'oht', 'water supply', 'water tanker', 'ro plant', 'building', 'vidhansouda'],
  },
];
const UNASSIGNED_CATEGORY = { key: 'unassigned', label: 'Unassigned & Others', color: '#757575' };
const ALL_CATEGORIES = [...CATEGORIES, UNASSIGNED_CATEGORY];

function categorizeWork(description) {
  const text = (description || '').toLowerCase();
  for (const category of CATEGORIES) {
    if (category.keywords.some((keyword) => text.includes(keyword))) return category.key;
  }
  return UNASSIGNED_CATEGORY.key;
}

function categoryMeta(key) {
  return ALL_CATEGORIES.find((category) => category.key === key) || UNASSIGNED_CATEGORY;
}

function renderCategoryRules() {
  categoryRulesList.innerHTML = ALL_CATEGORIES.map((category) => {
    const keywords = category.keywords ? category.keywords.join(', ') : '(fallback — no keywords matched)';
    return `<dt>${escapeHtml(category.label)}</dt><dd>${escapeHtml(keywords)}</dd>`;
  }).join('');
}
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
let segmentLayer = null;

const SEGMENT_CONFIDENCE_LABELS = {
  high: 'high confidence',
  medium: 'medium confidence — OCR-corrected job number match',
  low: 'low confidence',
};

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

// tendersir (v2.tendersir.pages.dev) exposes the same underlying BBMP payment records
// but keys its own detail pages by an internal numeric id we have no way to predict.
// It does support a `q=` search param that filters its list to the job number, which in
// practice surfaces the matching record (verified by hand for several job numbers) — so
// this is a search deep-link, not a guaranteed single-record match.
function tendersirSourceUrl(work) {
  return `https://v2.tendersir.pages.dev/?d=payments&q=${encodeURIComponent(work.job_number)}`;
}

function hasPoint(work) {
  return Number.isFinite(work.lat) && Number.isFinite(work.lng);
}

function hasSegments(work) {
  return Array.isArray(work.road_segments) && work.road_segments.length > 0;
}

function locatable(work) {
  return hasPoint(work) || hasSegments(work);
}

function segmentLatLngs(work) {
  return work.road_segments.flatMap((segment) => [
    [segment.start.lat, segment.start.lng],
    [segment.end.lat, segment.end.lng],
  ]);
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
  const locatedWorks = works.filter(locatable);
  if (locatedWorks.length === 0) {
    mapElement.classList.add('map-empty');
    mapElement.textContent =
      'No point coordinates or road segments are available in the current source data. Ward-level location labels are shown in the table.';
    mapLegend.textContent = '0 works with map geometry';
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
  segmentLayer = L.layerGroup().addTo(leafletMap);
  const points = locatedWorks.flatMap((work) => {
    const coords = hasPoint(work) ? [[work.lat, work.lng]] : [];
    return hasSegments(work) ? coords.concat(segmentLatLngs(work)) : coords;
  });
  const bounds = L.latLngBounds(points);
  leafletMap.fitBounds(bounds, { padding: [30, 30] });
  renderLegend();
}

function goToWork(work) {
  searchInput.value = work.job_number;
  applyFilters();
  document.getElementById('works-table').scrollIntoView({ behavior: 'smooth' });
}

function renderMap(works) {
  if (!markerLayer || !segmentLayer) return;
  markerLayer.clearLayers();
  segmentLayer.clearLayers();

  works.filter(hasPoint).forEach((work) => {
    const marker = L.marker([work.lat, work.lng], { icon: statusIcon(work.status) });
    marker.bindPopup(
      `<strong>${escapeHtml(work.job_number)}</strong><br>${escapeHtml(work.description)}<br>${escapeHtml(wardLabel(work))} &middot; ${escapeHtml(statusLabel(work.status))}<br>${currency.format(work.amount_gross)}`
    );
    marker.on('click', () => goToWork(work));
    marker.addTo(markerLayer);
  });

  works.filter(hasSegments).forEach((work) => {
    const color = STATUS_COLORS[work.status] || STATUS_COLORS.unknown;
    work.road_segments.forEach((segment) => {
      const confidenceLabel = SEGMENT_CONFIDENCE_LABELS[segment.confidence] || segment.confidence;
      const line = L.polyline(
        [
          [segment.start.lat, segment.start.lng],
          [segment.end.lat, segment.end.lng],
        ],
        {
          color,
          weight: 5,
          opacity: 0.8,
          // Dashed = not read with full confidence, per the "label uncertainty
          // visibly" rule — these are OCR readings off a scanned PDF, not
          // surveyed geometry.
          dashArray: segment.confidence === 'high' ? null : '6 6',
        }
      );
      const lengthText = Number.isFinite(segment.length_m) ? `${segment.length_m.toFixed(1)} m` : 'length unknown';
      line.bindPopup(
        `<strong>${escapeHtml(work.job_number)}</strong><br>${escapeHtml(work.description)}<br>` +
          `Segment ${escapeHtml(String(segment.segment_number))} &middot; ${escapeHtml(lengthText)}<br>` +
          `<em>${escapeHtml(confidenceLabel)}</em> &mdash; read by OCR off ${escapeHtml(segment.source_document)}, not a surveyed coordinate.`
      );
      line.on('click', () => goToWork(work));
      line.addTo(segmentLayer);
    });
  });
}

function renderLegend() {
  const statusItems = Object.entries(STATUS_COLORS)
    .map(
      ([status, color]) =>
        `<span class="legend-item"><span class="legend-dot" style="background:${color}"></span>${statusLabel(status)}</span>`
    )
    .join('');
  const segmentNote =
    '<span class="legend-item"><span class="legend-line legend-line-solid"></span>road segment, high confidence</span>' +
    '<span class="legend-item"><span class="legend-line legend-line-dashed"></span>road segment, OCR-corrected match</span>';
  mapLegend.innerHTML = statusItems + segmentNote;
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

function renderCategoryDonut(works) {
  const totals = {};
  works.forEach((work) => {
    totals[work.category] = (totals[work.category] || 0) + work.amount_gross;
  });
  const segments = ALL_CATEGORIES.filter((category) => totals[category.key]).map((category) => ({
    label: category.label,
    value: totals[category.key],
    color: category.color,
  }));
  renderDonut('category-donut', segments);
  renderDonutLegend(
    'category-donut-legend',
    segments.map((segment) => ({
      label: `${segment.label} (${currency.format(segment.value)})`,
      color: segment.color,
    }))
  );
}

function renderCategoryTotals(works) {
  const totals = {};
  const counts = {};
  works.forEach((work) => {
    totals[work.category] = (totals[work.category] || 0) + work.amount_gross;
    counts[work.category] = (counts[work.category] || 0) + 1;
  });
  const ranked = ALL_CATEGORIES.filter((category) => counts[category.key]).sort(
    (left, right) => totals[right.key] - totals[left.key]
  );
  categoryTotalsBody.innerHTML = ranked
    .map(
      (category) => `
    <tr>
      <td><span class="legend-dot" style="background:${category.color}"></span> ${escapeHtml(category.label)}${
        category.keywords
          ? ` <span class="category-keywords">(${escapeHtml(category.keywords.join(', '))})</span>`
          : ''
      }</td>
      <td>${counts[category.key].toLocaleString('en-IN')}</td>
      <td>${currency.format(totals[category.key])}</td>
    </tr>`
    )
    .join('');
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
      <td><a href="${tendersirSourceUrl(work)}" target="_blank" rel="noopener noreferrer" title="Searches tendersir by job number — not a guaranteed exact match">tendersir ↗</a></td>
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
  renderCategoryDonut(works);
  renderCategoryTotals(works);
}

function populateFilters(works) {
  const wards = [...new Set(works.map(wardLabel))].sort();
  const statuses = [...new Set(works.map((work) => work.status))].sort();
  const presentCategories = new Set(works.map((work) => work.category));
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
  categoryFilter.innerHTML =
    '<option value="">All categories</option>' +
    ALL_CATEGORIES.filter((category) => presentCategories.has(category.key))
      .map((category) => `<option value="${category.key}">${escapeHtml(category.label)}</option>`)
      .join('');
}

function applyFilters() {
  const needle = searchInput.value.trim().toLowerCase();
  const ward = wardFilter.value;
  const status = statusFilter.value;
  const category = categoryFilter.value;
  const filtered = allWorks.filter((work) => {
    if (ward && wardLabel(work) !== ward) return false;
    if (status && work.status !== status) return false;
    if (category && work.category !== category) return false;
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
    allWorks.forEach((work) => {
      work.category = categorizeWork(work.description);
    });
    dataBanner.textContent =
      `Source data through ${payload.meta.as_of_date}: ${payload.meta.record_count.toLocaleString('en-IN')} works. Tender links and exact coordinates remain unavailable where the source cannot support them.`;
    initMap(allWorks);
    renderCategoryRules();
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
categoryFilter.addEventListener('change', applyFilters);

init();
