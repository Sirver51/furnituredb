const PLACEHOLDER_IMG =
  'data:image/svg+xml,' +
  encodeURIComponent(
    '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="160">' +
      '<rect width="100%" height="100%" fill="#eee"/>' +
      '<text x="50%" y="50%" dominant-baseline="middle" text-anchor="middle" ' +
      'fill="#999" font-family="sans-serif" font-size="14">No image</text>' +
      '</svg>'
  );

function imgUrl(imageId) {
  return imageId ? `/img/${imageId}` : PLACEHOLDER_IMG;
}

function escapeHtml(s) {
  const div = document.createElement('div');
  div.textContent = s ?? '';
  return div.innerHTML;
}

async function loadMeta() {
  const res = await fetch('/api/meta');
  const meta = await res.json();

  const select = document.getElementById('site-filter');
  for (const site of meta.sites) {
    const opt = document.createElement('option');
    opt.value = site;
    opt.textContent = site;
    select.appendChild(opt);
  }

  const status = document.getElementById('status');
  status.textContent =
    `${meta.product_count.toLocaleString()} products` +
    ` | text embeddings: ${meta.embeddings.text.toLocaleString()}` +
    ` | image embeddings: ${meta.embeddings.image.toLocaleString()}`;

  return meta;
}

function attachProductLinkHandler(el, productId) {
  el.addEventListener('click', (e) => {
    if (e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    navigateToProduct(productId);
  });
}

function renderCard(card) {
  const el = document.createElement('a');
  el.className = 'card';
  el.href = `#product=${card.id}`;
  const simBadge =
    card.similarity != null ? `<span class="similarity">${card.similarity}%</span>` : '';
  el.innerHTML = `
    <div class="card-img-wrap">
      <img src="${imgUrl(card.image_id)}" loading="lazy" alt="${escapeHtml(card.name)}">
      ${simBadge}
    </div>
    <div class="card-body">
      <div class="card-name">${escapeHtml(card.name)}</div>
      <div class="card-meta">
        <span class="badge">${escapeHtml(card.site)}</span>
        ${card.price != null ? `<span class="price">${escapeHtml(card.currency || 'AED')} ${card.price}</span>` : ''}
      </div>
    </div>
  `;
  attachProductLinkHandler(el, card.id);
  return el;
}

let lastResults = [];

function passesThreshold(card, threshold) {
  const sim = card.similarity != null ? card.similarity : 0;
  return sim >= threshold;
}

function renderResults() {
  const threshold = Number(document.getElementById('similarity-threshold').value);
  const results = document.getElementById('results');
  results.innerHTML = '';

  let shown = 0;
  for (const card of lastResults) {
    if (!passesThreshold(card, threshold)) continue;
    results.appendChild(renderCard(card));
    shown++;
  }

  const info = document.getElementById('results-info');
  if (lastResults.length === 0) {
    info.textContent = '';
  } else if (threshold > 0) {
    info.textContent = `Showing ${shown} of ${lastResults.length} results (>= ${threshold}% similarity)`;
  } else {
    info.textContent = `${shown} results`;
  }
}

async function doSearch(e) {
  e.preventDefault();

  const q = document.getElementById('q').value.trim();
  const imageFile = document.getElementById('image-input').files[0];
  const site = document.getElementById('site-filter').value;
  const priceMin = document.getElementById('price-min').value;
  const priceMax = document.getElementById('price-max').value;

  if (!q && !imageFile) return;

  const form = new FormData();
  if (q) form.append('q', q);
  if (imageFile) form.append('image', imageFile);
  if (site) form.append('site', site);
  if (priceMin) form.append('price_min', priceMin);
  if (priceMax) form.append('price_max', priceMax);

  const status = document.getElementById('status');
  status.textContent = 'Searching...';

  const res = await fetch('/api/search', { method: 'POST', body: form });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    status.textContent = `Search failed: ${err.detail || res.statusText}`;
    return;
  }
  const data = await res.json();

  lastResults = data.results;
  renderResults();

  const bits = [];
  if (data.info.lexical != null) bits.push(`lexical: ${data.info.lexical}`);
  if (data.info.semantic != null) bits.push(`semantic: ${data.info.semantic}`);
  if (data.info.visual != null) bits.push(`visual: ${data.info.visual}`);
  if (data.info.cross_modal != null) bits.push(`cross-modal: ${data.info.cross_modal}`);
  if (data.info.error) bits.push(`error: ${data.info.error}`);
  if (data.info.semantic_error) bits.push(`semantic unavailable: ${data.info.semantic_error}`);
  status.textContent = bits.join(' | ');

  showSearchView();
}

async function showDetail(productId) {
  const res = await fetch(`/api/product/${productId}`);
  if (!res.ok) return;
  const product = await res.json();
  renderDetail(product);

  document.getElementById('search-view').classList.add('hidden');
  document.getElementById('graph-view').classList.add('hidden');
  document.getElementById('detail-view').classList.remove('hidden');
  window.scrollTo(0, 0);
}

function renderDetail(product) {
  const content = document.getElementById('detail-content');

  const images = product.images.length
    ? product.images.map((img) => `<img src="/img/${img.id}" loading="lazy" alt="">`).join('')
    : `<img src="${PLACEHOLDER_IMG}" alt="">`;

  const attrs = product.attributes
    .map((a) => `<tr><td>${escapeHtml(a.name_raw)}</td><td>${escapeHtml(a.value_raw ?? '')}</td></tr>`)
    .join('');

  const variants = product.variants
    .map(
      (v) =>
        `<li><a href="#product=${v.id}" data-id="${v.id}">${escapeHtml(v.name)}${
          v.price != null ? ` &mdash; ${escapeHtml(v.currency || 'AED')} ${v.price}` : ''
        }</a></li>`
    )
    .join('');

  content.innerHTML = `
    <div class="detail-grid">
      <div class="gallery">${images}</div>
      <div class="info">
        <span class="badge">${escapeHtml(product.site)}</span>
        <h2>${escapeHtml(product.name)}</h2>
        ${product.price != null ? `<div class="price">${escapeHtml(product.currency || 'AED')} ${product.price}</div>` : ''}
        ${product.taxonomy_path ? `<div class="breadcrumb">${escapeHtml(product.taxonomy_path)}</div>` : ''}
        ${product.url ? `<a class="site-link" href="${escapeHtml(product.url)}" target="_blank" rel="noopener">View on site &rarr;</a>` : ''}
        ${product.description ? `<p class="description">${escapeHtml(product.description)}</p>` : ''}
        <button id="browse-graph-btn">Browse adjacent (graph)</button>
        ${variants.length ? `<h3>Variants</h3><ul class="variants">${variants}</ul>` : ''}
        ${attrs.length ? `<h3>Attributes</h3><table class="attrs"><tbody>${attrs}</tbody></table>` : ''}
      </div>
    </div>
  `;

  document.getElementById('browse-graph-btn').addEventListener('click', () => openGraph(product.id));

  content.querySelectorAll('.variants a').forEach((a) => {
    attachProductLinkHandler(a, parseInt(a.dataset.id, 10));
  });
}

function showSearchView() {
  document.getElementById('search-view').classList.remove('hidden');
  document.getElementById('detail-view').classList.add('hidden');
  document.getElementById('graph-view').classList.add('hidden');
}

function navigateToProduct(productId) {
  const target = `product=${productId}`;
  if (location.hash === `#${target}`) {
    showDetail(productId);
  } else {
    location.hash = target;
  }
}

function goToSearchView() {
  if (location.hash) {
    location.hash = '';
  } else {
    showSearchView();
  }
}

function routeFromHash() {
  const m = location.hash.match(/^#product=(\d+)$/);
  if (m) {
    showDetail(parseInt(m[1], 10));
  } else {
    showSearchView();
  }
}

document.getElementById('search-form').addEventListener('submit', doSearch);
document.getElementById('back-btn').addEventListener('click', goToSearchView);
document.getElementById('back-from-graph').addEventListener('click', goToSearchView);

document.getElementById('image-input').addEventListener('change', (e) => {
  const label = document.getElementById('image-name');
  label.textContent = e.target.files[0] ? e.target.files[0].name : 'Search by image';
});

const thresholdInput = document.getElementById('similarity-threshold');
thresholdInput.addEventListener('input', () => {
  document.getElementById('similarity-value').textContent = `${thresholdInput.value}%`;
  renderResults();
});

window.addEventListener('hashchange', routeFromHash);

loadMeta();
routeFromHash();
