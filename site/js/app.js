/* Balseiro Alumni Atlas — front-end (vanilla JS + Leaflet) */
'use strict';

const DATA_URL = 'data/alumni.json';
const ORCID_BASE = 'https://orcid.org/';
const SCHOLAR_BASE = 'https://scholar.google.com/citations?user=';

let ALUMNI = [];
let META = {};
let map, cluster, zoomControlAdded = false;

const state = {
  q: '',
  region: 'all',
  facets: { discipline: new Set(), sector: new Set(), program: new Set(),
            grad_decade: new Set(), country: new Set(), sources: new Set() },
  view: 'map',
  sort: { key: 'name', dir: 1 },
};

const FACETS = [
  { key: 'discipline', label: 'Research field',      values: p => p.discipline ? [p.discipline] : [], open: true },
  { key: 'sector',     label: 'Type of employer',    values: p => p.sector ? [p.sector] : [],         open: true },
  { key: 'country',    label: 'Country (now)',       values: p => p.country ? [p.country] : [],       open: true },
  { key: 'program',    label: 'Degree at Balseiro',  values: p => p.program ? [p.program] : [],       open: false },
  { key: 'grad_decade',label: 'Graduation decade',   values: p => p.grad_decade ? [p.grad_decade + 's'] : [], open: false },
  { key: 'sources',    label: 'Data source',         values: p => p.sources || [],                    open: false },
];

/* ------------------------------------------------------------------ */
/* boot                                                                */
/* ------------------------------------------------------------------ */
fetch(DATA_URL)
  .then(r => r.json())
  .then(payload => {
    META = payload.meta || {};
    ALUMNI = payload.alumni || [];
    initMap();
    buildHeadline();
    buildAbout();
    buildFacets();
    wireControls();
    refresh();
  })
  .catch(err => {
    document.getElementById('main').innerHTML =
      `<div style="padding:40px;max-width:640px">
         <h2>Could not load the alumni data</h2>
         <p>Expected <code>${DATA_URL}</code>. Run the pipeline first:</p>
         <pre>python3 scripts/run_all.py</pre>
         <p style="color:#a33">${err}</p>
       </div>`;
  });

/* ------------------------------------------------------------------ */
/* map                                                                 */
/* ------------------------------------------------------------------ */
function initMap() {
  const dark = window.matchMedia('(prefers-color-scheme: dark)').matches;
  map = L.map('map', { worldCopyJump: true, minZoom: 2 }).setView([20, 5], 2);
  // Esri's gray canvas — muted, good for data overlays, and free with no API key.
  const style = dark ? 'World_Dark_Gray_Base' : 'World_Light_Gray_Base';
  const esri = L.tileLayer(
    `https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/${style}/MapServer/tile/{z}/{y}/{x}`,
    { attribution: 'Tiles &copy; Esri', maxZoom: 16 }
  );
  esri.on('tileerror', () => {
    if (map.hasLayer(esri)) map.removeLayer(esri);
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',
      { attribution: '&copy; OpenStreetMap contributors', maxZoom: 19 }).addTo(map);
  });
  esri.addTo(map);

  cluster = L.markerClusterGroup({
    maxClusterRadius: 44,
    spiderfyOnMaxZoom: true,
    showCoverageOnHover: false,
  });
  map.addLayer(cluster);

  // home base
  L.circleMarker([-41.1335, -71.4281], {
    radius: 7, weight: 2, color: '#a51f1f', fillColor: '#d64545', fillOpacity: 0.9,
  }).addTo(map).bindPopup(
    '<div class="pp"><div class="pp-name">Instituto Balseiro</div>' +
    '<div class="pp-role">San Carlos de Bariloche, Río Negro, Argentina</div>' +
    '<div class="pp-line">Centro Atómico Bariloche — where every person on this map studied.</div></div>'
  );

  const ZoomBtn = L.Control.extend({
    options: { position: 'topleft' },
    onAdd() {
      const b = L.DomUtil.create('button', 'leaflet-bar');
      b.title = 'Zoom to current results';
      b.textContent = '⤢';
      Object.assign(b.style, { width: '34px', height: '34px', fontSize: '16px', background: 'var(--surface)', color: 'var(--text)' });
      L.DomEvent.on(b, 'click', e => { L.DomEvent.stop(e); zoomToResults(); });
      return b;
    },
  });
  map.addControl(new ZoomBtn());
}

function markerFor(p) {
  const abroad = p.country && p.country !== 'Argentina';
  const m = L.circleMarker([p.lat, p.lon], {
    radius: 6, weight: 1.5,
    color: abroad ? '#c98432' : '#3f6fae',
    fillColor: abroad ? '#e0a458' : '#6c9bd1',
    fillOpacity: 0.85,
  });
  m.bindPopup(popupHtml(p), { minWidth: 250 });
  return m;
}

function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function popupHtml(p) {
  const links = [];
  if (p.wikipedia) links.push(`<a href="${esc(p.wikipedia)}" target="_blank" rel="noopener">Wikipedia</a>`);
  if (p.orcid) links.push(`<a href="${ORCID_BASE}${esc(p.orcid)}" target="_blank" rel="noopener">ORCID</a>`);
  if (p.scholar_id) links.push(`<a href="${SCHOLAR_BASE}${esc(p.scholar_id)}" target="_blank" rel="noopener">Scholar</a>`);
  if (p.urls && p.urls[0]) links.push(`<a href="${esc(p.urls[0])}" target="_blank" rel="noopener">Homepage</a>`);
  if (p.wikidata) links.push(`<a href="${esc(p.wikidata)}" target="_blank" rel="noopener">Wikidata</a>`);

  const chips = [];
  if (p.discipline && p.discipline !== 'Not specified') chips.push(`<span class="chip">${esc(p.discipline)}</span>`);
  if (p.sector) chips.push(`<span class="chip muted">${esc(p.sector)}</span>`);
  if (p.grad_year) chips.push(`<span class="chip muted">IB ${esc(p.grad_year)}</span>`);

  const photo = p.image
    ? `<img class="pp-photo" src="${esc(p.image)}" alt="" loading="lazy"
         onerror="this.style.display='none'">`
    : `<div class="pp-photo"></div>`;

  return `<div class="pp">
    <div class="pp-head">${photo}
      <div>
        <div class="pp-name">${esc(p.name)}${p.deceased ? ' †' : ''}</div>
        <div class="pp-role">${esc(p.role || p.description || '')}</div>
      </div>
    </div>
    <div class="pp-line"><b>${esc(p.employer || 'Unknown employer')}</b><br>
      ${esc([p.city, p.country].filter(Boolean).join(', '))}</div>
    ${chips.length ? `<div class="pp-chips">${chips.join('')}</div>` : ''}
    ${links.length ? `<div class="pp-links">${links.join('')}</div>` : ''}
  </div>`;
}

/* ------------------------------------------------------------------ */
/* filtering                                                           */
/* ------------------------------------------------------------------ */
function matches(p, ignoreKey) {
  if (state.q) {
    const hay = [
      p.name, p.employer, p.role, p.description, p.discipline, p.city, p.country,
      (p.keywords || []).join(' '), (p.fields || []).join(' '), (p.aka || []).join(' '),
    ].join(' ').toLowerCase();
    if (!hay.includes(state.q)) return false;
  }
  if (state.region === 'ar' && p.country !== 'Argentina') return false;
  if (state.region === 'abroad' && (!p.country || p.country === 'Argentina')) return false;

  for (const f of FACETS) {
    if (f.key === ignoreKey) continue;
    const sel = state.facets[f.key];
    if (!sel.size) continue;
    const vals = f.values(p).map(String);
    if (!vals.some(v => sel.has(v))) return false;
  }
  return true;
}

function filtered(ignoreKey) {
  return ALUMNI.filter(p => matches(p, ignoreKey));
}

/* ------------------------------------------------------------------ */
/* headline + about                                                    */
/* ------------------------------------------------------------------ */
function buildHeadline() {
  const el = document.getElementById('headline-stats');
  el.innerHTML = `
    <div class="stat"><div class="num" id="hs-people">${META.total}</div><div class="lbl">alumni</div></div>
    <div class="stat"><div class="num" id="hs-countries">${META.countries}</div><div class="lbl">countries</div></div>
    <div class="stat"><div class="num" id="hs-mapped">${META.located}</div><div class="lbl">on the map</div></div>`;
}

function buildAbout() {
  const s = META.sources || {};
  document.getElementById('about-panel').innerHTML = `
    <h3>About this atlas</h3>
    <p>${esc(META.disclaimer || '')}</p>
    <ul>
      <li>Sources: Wikidata ${s.wikidata || 0} · ORCID ${s.orcid || 0} · Wikipedia ${s.wikipedia || 0} · hand-added ${s.manual || 0}</li>
      <li>Generated ${esc((META.generated || '').replace('T', ' ').replace('+00:00', ' UTC'))}</li>
      <li>Add people yourself in <code>data/manual_alumni.csv</code>, then re-run <code>python3 scripts/run_all.py</code>.</li>
    </ul>`;
}

/* ------------------------------------------------------------------ */
/* facets                                                              */
/* ------------------------------------------------------------------ */
function buildFacets() {
  const host = document.getElementById('facets');
  host.innerHTML = '';
  for (const f of FACETS) {
    const universe = new Map();
    for (const p of ALUMNI) for (const v of f.values(p)) universe.set(String(v), (universe.get(String(v)) || 0) + 1);
    const sorted = [...universe.entries()].sort((a, b) =>
      f.key === 'grad_decade' ? a[0].localeCompare(b[0]) : b[1] - a[1]);

    const det = document.createElement('details');
    det.className = 'facet';
    det.open = f.open;
    det.innerHTML = `<summary>${f.label}</summary>
      <div class="facet-options">${sorted.map(([v]) => `
        <label class="opt" data-facet="${f.key}" data-value="${esc(v)}">
          <input type="checkbox">
          <span class="opt-label">${esc(v)}</span>
          <span class="count"></span>
        </label>`).join('')}</div>`;
    host.appendChild(det);
  }
  host.addEventListener('change', e => {
    const lab = e.target.closest('.opt');
    if (!lab) return;
    const set = state.facets[lab.dataset.facet];
    e.target.checked ? set.add(lab.dataset.value) : set.delete(lab.dataset.value);
    refresh();
  });
}

function updateFacetCounts() {
  for (const f of FACETS) {
    const subset = filtered(f.key);
    const counts = new Map();
    for (const p of subset) for (const v of f.values(p)) counts.set(String(v), (counts.get(String(v)) || 0) + 1);
    document.querySelectorAll(`.opt[data-facet="${f.key}"]`).forEach(lab => {
      const n = counts.get(lab.dataset.value) || 0;
      lab.querySelector('.count').textContent = n;
      lab.classList.toggle('disabled', n === 0 && !state.facets[f.key].has(lab.dataset.value));
    });
  }
}

/* ------------------------------------------------------------------ */
/* controls                                                            */
/* ------------------------------------------------------------------ */
function wireControls() {
  const search = document.getElementById('search');
  let searchTimer;
  search.addEventListener('input', () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      state.q = search.value.trim().toLowerCase();
      refresh();
    }, 150);
  });

  document.getElementById('region-toggle').addEventListener('click', e => {
    const b = e.target.closest('button'); if (!b) return;
    state.region = b.dataset.region;
    [...e.currentTarget.children].forEach(c => c.classList.toggle('active', c === b));
    refresh();
  });

  document.getElementById('view-tabs').addEventListener('click', e => {
    const b = e.target.closest('button'); if (!b) return;
    setView(b.dataset.view);
  });

  document.getElementById('about-toggle').addEventListener('click', () => {
    const p = document.getElementById('about-panel');
    p.hidden = !p.hidden;
  });

  document.getElementById('reset').addEventListener('click', () => {
    state.q = ''; search.value = '';
    state.region = 'all';
    document.querySelectorAll('#region-toggle button').forEach(b => b.classList.toggle('active', b.dataset.region === 'all'));
    for (const k in state.facets) state.facets[k].clear();
    document.querySelectorAll('#facets input[type=checkbox]').forEach(c => (c.checked = false));
    refresh();
  });

  const mfb = document.createElement('button');
  mfb.className = 'mobile-filter-btn';
  mfb.textContent = 'Filters';
  mfb.addEventListener('click', () => document.getElementById('sidebar').classList.toggle('open'));
  document.getElementById('view-map').appendChild(mfb);
}

function setView(v) {
  state.view = v;
  document.querySelectorAll('#view-tabs button').forEach(b => b.classList.toggle('active', b.dataset.view === v));
  document.getElementById('view-map').hidden = v !== 'map';
  document.getElementById('view-insights').hidden = v !== 'insights';
  document.getElementById('view-list').hidden = v !== 'list';
  if (v === 'map') setTimeout(() => map.invalidateSize(), 50);
  if (v === 'insights') renderInsights();
  if (v === 'list') renderList();
}

/* ------------------------------------------------------------------ */
/* refresh + render                                                    */
/* ------------------------------------------------------------------ */
function refresh() {
  const res = filtered(null);
  const located = res.filter(p => p.located);

  cluster.clearLayers();
  cluster.addLayers(located.map(markerFor));

  const unmapped = res.length - located.length;
  document.getElementById('unmapped-note').textContent =
    `${located.length} of ${res.length} shown on map` + (unmapped ? ` · ${unmapped} without a known location` : '');
  document.getElementById('result-count').textContent =
    `${res.length} ${res.length === 1 ? 'person' : 'people'}`;

  updateFacetCounts();
  if (state.view === 'insights') renderInsights();
  if (state.view === 'list') renderList();
}

function zoomToResults() {
  const pts = filtered(null).filter(p => p.located).map(p => [p.lat, p.lon]);
  if (pts.length) map.fitBounds(L.latLngBounds(pts).pad(0.15), { maxZoom: 12 });
}

/* ------------------------------------------------------------------ */
/* insights                                                            */
/* ------------------------------------------------------------------ */
function tally(list, keyFn) {
  const m = new Map();
  for (const p of list) {
    for (const k of [].concat(keyFn(p))) {
      if (k == null || k === '') continue;
      m.set(k, (m.get(k) || 0) + 1);
    }
  }
  return [...m.entries()].sort((a, b) => b[1] - a[1]);
}

function barChart(rows, { max, cls, onClick }) {
  const top = max ? rows.slice(0, max) : rows;
  const peak = top.length ? top[0][1] : 1;
  return top.map(([label, n]) => `
    <div class="bar-row">
      <span class="bl" ${onClick ? `data-filter="${esc(label)}"` : ''}>${esc(label)}</span>
      <span class="bar-track"><span class="bar-fill ${cls || ''}" style="width:${(n / peak * 100).toFixed(1)}%"></span></span>
      <span class="bv">${n}</span>
    </div>`).join('');
}

function renderInsights() {
  const list = filtered(null);
  const host = document.getElementById('view-insights');

  const withCountry = list.filter(p => p.country);
  const inAR = withCountry.filter(p => p.country === 'Argentina').length;
  const abroad = withCountry.length - inAR;
  const pctAbroad = withCountry.length ? Math.round(abroad / withCountry.length * 100) : 0;

  const countries = tally(list, p => p.country);
  const employers = tally(list, p => p.employer);
  const disciplines = tally(list, p => p.discipline);
  const sectors = tally(list, p => p.sector);
  const decades = tally(list, p => p.grad_decade ? p.grad_decade + 's' : null)
    .sort((a, b) => a[0].localeCompare(b[0]));
  const multiEmployers = employers.filter(([, n]) => n >= 2);

  const splitBar = (parts) => {
    const total = parts.reduce((s, [, n]) => s + n, 0) || 1;
    return `<div class="split">${parts.map(([lbl, n, color]) =>
      `<span style="flex:${n};background:${color}" title="${esc(lbl)}: ${n}">${n / total > 0.08 ? n : ''}</span>`).join('')}</div>`;
  };

  host.innerHTML = `
   <div class="insights-grid">
    <div class="card">
      <h3>Argentina vs. abroad</h3>
      <p class="sub">of ${withCountry.length} people with a known current country</p>
      <div class="big-figure">${pctAbroad}%</div>
      <p class="callout">work outside Argentina${state.q || anyFacet() ? ' (within the current filter)' : ''}.</p>
      ${splitBar([['In Argentina', inAR, 'var(--argentina)'], ['Abroad', abroad, 'var(--abroad)']])}
    </div>

    <div class="card">
      <h3>Top destination countries</h3>
      <p class="sub">click a bar to filter the map</p>
      ${barChart(countries, { max: 12, onClick: true })}
    </div>

    <div class="card">
      <h3>Where they work — employers</h3>
      <p class="sub">${multiEmployers.length} institutions employ 2+ alumni · click to filter</p>
      ${barChart(employers, { max: 14, onClick: true })}
    </div>

    <div class="card">
      <h3>Research fields</h3>
      ${barChart(disciplines, { max: 12 })}
    </div>

    <div class="card">
      <h3>Type of employer</h3>
      ${barChart(sectors, { max: 8 })}
    </div>

    <div class="card">
      <h3>When they graduated</h3>
      <p class="sub">${list.filter(p => p.grad_year).length} with a known graduation year</p>
      ${barChart(decades, {})}
    </div>
   </div>`;

  host.querySelectorAll('[data-filter]').forEach(el => {
    el.addEventListener('click', () => {
      const val = el.dataset.filter;
      const asCountry = countries.some(([c]) => c === val);
      const key = asCountry ? 'country' : null;
      if (key) {
        state.facets.country.clear();
        state.facets.country.add(val);
        syncCheckboxes();
      } else {
        document.getElementById('search').value = val;
        state.q = val.toLowerCase();
      }
      setView('map');
      refresh();
      setTimeout(zoomToResults, 150);
    });
  });
}

function anyFacet() { return Object.values(state.facets).some(s => s.size); }

function syncCheckboxes() {
  document.querySelectorAll('#facets .opt').forEach(lab => {
    lab.querySelector('input').checked = state.facets[lab.dataset.facet].has(lab.dataset.value);
  });
}

/* ------------------------------------------------------------------ */
/* list                                                                */
/* ------------------------------------------------------------------ */
const COLS = [
  { key: 'name', label: 'Name' },
  { key: 'role', label: 'Role' },
  { key: 'employer', label: 'Employer' },
  { key: 'country', label: 'Location' },
  { key: 'discipline', label: 'Field' },
  { key: 'grad_year', label: 'IB' },
];

function renderList() {
  const rows = filtered(null).slice().sort((a, b) => {
    const { key, dir } = state.sort;
    let x = a[key], y = b[key];
    if (x == null) return 1;
    if (y == null) return -1;
    if (typeof x === 'string') return x.localeCompare(y) * dir;
    return (x - y) * dir;
  });

  const body = rows.map(p => {
    const loc = [p.city, p.country].filter(Boolean).join(', ') || '—';
    const tag = p.country === 'Argentina' ? 'tag-ar' : (p.country ? 'tag-abroad' : '');
    const link = p.wikipedia || (p.orcid ? ORCID_BASE + p.orcid : (p.urls && p.urls[0])) || p.wikidata;
    return `<tr>
      <td class="nm">${link ? `<a href="${esc(link)}" target="_blank" rel="noopener">${esc(p.name)}</a>` : esc(p.name)}</td>
      <td class="subtle">${esc(p.role || p.description || '—')}</td>
      <td>${esc(p.employer || '—')}</td>
      <td class="${tag}">${esc(loc)}</td>
      <td class="subtle">${esc(p.discipline === 'Not specified' ? '—' : p.discipline || '—')}</td>
      <td class="subtle">${p.grad_year || '—'}</td>
    </tr>`;
  }).join('');

  document.getElementById('list-container').innerHTML = `
    <table class="people">
      <thead><tr>${COLS.map(c =>
        `<th data-key="${c.key}">${c.label}${state.sort.key === c.key ? (state.sort.dir > 0 ? ' ▲' : ' ▼') : ''}</th>`).join('')}</tr></thead>
      <tbody>${body}</tbody>
    </table>`;

  document.querySelectorAll('.people th').forEach(th => th.addEventListener('click', () => {
    const k = th.dataset.key;
    state.sort = { key: k, dir: state.sort.key === k ? -state.sort.dir : 1 };
    renderList();
  }));
}
