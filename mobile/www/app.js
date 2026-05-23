'use strict';

const API       = 'https://pulse.lavkesh.com/newsletter.json';
const CACHE_KEY = 'gp_cache_v1';
const LANG_KEY  = 'gp_lang';
const THEME_KEY = 'gp_theme';
const APP_VER   = '1.0.0';

const REGIONS = ['All','Asia-Pacific','Europe & Russia','Middle East & Africa','Americas','Global / Multilateral'];


// Normalise legacy/catch-all region tags to their canonical display names
function normaliseRegion(r) {
  if (r === 'World') return 'Global / Multilateral';
  return r;
}

// ── State ─────────────────────────────────────────────────────────────────────
let nl       = null;
let lang     = store(LANG_KEY)  || 'en';
let region   = 'All';
let theme    = store(THEME_KEY) || 'system';
let fetching = false;

// ── DOM ───────────────────────────────────────────────────────────────────────
const feed     = document.getElementById('feed');
const navEl    = document.getElementById('region-nav');
const ageEl    = document.getElementById('age');
const btnLang  = document.getElementById('btn-lang');
const btnTheme = document.getElementById('btn-theme');
const btnMore  = document.getElementById('btn-more');
const ptr      = document.getElementById('ptr');
const sheet    = document.getElementById('sheet');
const sheetBg  = document.getElementById('sheet-bg');

// ── Helpers ───────────────────────────────────────────────────────────────────
function store(k, v) {
  try {
    if (v !== undefined) { localStorage.setItem(k, v); return; }
    return localStorage.getItem(k);
  } catch { return null; }
}

function esc(s) {
  return (s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function ago(iso) {
  if (!iso) return '';
  const m = Math.floor((Date.now() - new Date(iso)) / 60000);
  if (m < 1)  return 'just now';
  if (m < 60) return m + 'm ago';
  const h = Math.floor(m / 60);
  if (h < 24) return h + 'h ago';
  return Math.floor(h / 24) + 'd ago';
}

function tr(a, key) {
  const hi = a.translations?.hi?.[key];
  return (lang === 'hi' && hi) ? hi : (a[key] || '');
}

function visibleArticles() {
  if (!nl) return [];
  return nl.articles.filter(a =>
    a.language === lang && (region === 'All' || normaliseRegion(a.region) === region)
  );
}

function usedRegions() {
  if (!nl) return REGIONS;
  const used = new Set(nl.articles.filter(a => a.language === lang).map(a => normaliseRegion(a.region)));
  return ['All', ...REGIONS.slice(1).filter(r => used.has(r))];
}

// ── Theme ─────────────────────────────────────────────────────────────────────
const MOON = `<svg viewBox="0 0 24 24"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>`;
const SUN  = `<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>`;

function isDark() {
  return theme === 'dark' ||
    (theme === 'system' && matchMedia('(prefers-color-scheme: dark)').matches);
}

function applyTheme() {
  document.documentElement.toggleAttribute('data-dark', isDark());
  btnTheme.innerHTML = isDark() ? SUN : MOON;
}

btnTheme.onclick = () => {
  theme = isDark() ? 'light' : 'dark';
  store(THEME_KEY, theme);
  applyTheme();
};

matchMedia('(prefers-color-scheme: dark)').onchange = () => {
  if (theme === 'system') applyTheme();
};

// ── Language ──────────────────────────────────────────────────────────────────
function applyLang() {
  btnLang.textContent = lang === 'en' ? 'हिंदी' : 'EN';
  const available = usedRegions();
  if (!available.includes(region)) region = 'All';
  render();
}

btnLang.onclick = () => {
  lang = lang === 'en' ? 'hi' : 'en';
  store(LANG_KEY, lang);
  applyLang();
};

// ── Bottom Sheet ──────────────────────────────────────────────────────────────
function openSheet() {
  const age = nl?.generated_at ? ago(nl.generated_at) : '—';
  document.getElementById('sheet-age').textContent = age;
  sheet.classList.add('open');
  sheetBg.classList.add('open');
}

function closeSheet() {
  sheet.classList.remove('open');
  sheetBg.classList.remove('open');
}

btnMore.onclick = openSheet;
sheetBg.onclick = closeSheet;

document.getElementById('sheet-refresh').onclick = () => {
  closeSheet();
  doRefresh();
};

document.getElementById('sheet-close').onclick = closeSheet;

// ── Open article ──────────────────────────────────────────────────────────────
function openUrl(url) {
  window.open(url, '_blank');
}

// ── Render ────────────────────────────────────────────────────────────────────
function renderTabs() {
  const tabs = usedRegions();
  navEl.innerHTML = tabs.map(r =>
    `<button class="tab${r === region ? ' on' : ''}" data-r="${esc(r)}">${esc(r)}</button>`
  ).join('');
  navEl.querySelectorAll('.tab').forEach(b => {
    b.onclick = () => {
      region = b.dataset.r;
      b.scrollIntoView({ behavior: 'smooth', inline: 'center', block: 'nearest' });
      renderTabs();
      renderFeed();
    };
  });
}

function renderFeed() {
  if (!nl && fetching) {
    feed.innerHTML = `<div class="cbox"><div class="spinner"></div></div>`;
    return;
  }

  if (!nl) {
    feed.innerHTML = `
      <div class="cbox">
        <div class="err-icon">📡</div>
        <div class="err-title">Could not load news</div>
        <div class="err-sub">Check your connection and pull down to retry.</div>
        <button class="retry-btn" onclick="doRefresh()">Try again</button>
      </div>`;
    return;
  }

  const list   = visibleArticles();
  const digest = nl.digest?.[lang] || nl.digest?.en || '';
  let h = '';

  if (digest) {
    h += `
      <div class="digest">
        <span class="digest-icon">✍️</span>
        <span class="digest-text">${esc(digest)}</span>
      </div>`;
  }

  if (!list.length) {
    h += `<div class="cbox"><span style="color:var(--text3);font-size:14px">No stories in this region right now.</span></div>`;
  } else {
    h += list.map(a => {
      const displayRegion = normaliseRegion(a.region);
      const img = a.image_url
        ? `<img class="card-img" src="${esc(a.image_url)}" alt="" loading="lazy" onerror="this.remove()">`
        : '';
      return `
        <div class="card" data-url="${esc(a.url)}">
          ${img}
          <div class="card-body">
            <div class="card-meta">
              <span class="chip">${esc(displayRegion)}</span>
              ${a.published_at ? `<span class="card-time">${ago(a.published_at)}</span>` : ''}
            </div>
            <div class="card-title">${esc(tr(a,'title'))}</div>
            <div class="card-summary">${esc(tr(a,'summary'))}</div>
            <div class="card-source">${esc(a.source)}</div>
          </div>
        </div>`;
    }).join('');
  }

  feed.innerHTML = h;
}

// Event delegation — one listener for all cards
feed.addEventListener('click', e => {
  const card = e.target.closest('.card');
  if (card?.dataset.url) openUrl(card.dataset.url);
});

function render() {
  renderTabs();
  renderFeed();
  if (nl?.generated_at) ageEl.textContent = ago(nl.generated_at);
}

// ── Data ──────────────────────────────────────────────────────────────────────
async function load(force = false) {
  if (!force) {
    try {
      const cached = JSON.parse(store(CACHE_KEY) || 'null');
      if (cached) { nl = cached; render(); }
    } catch {}
  }

  fetching = true;
  if (!nl) render();

  try {
    const res = await fetch(API + '?_=' + Date.now());
    if (!res.ok) throw new Error('HTTP ' + res.status);
    nl = await res.json();
    try { store(CACHE_KEY, JSON.stringify(nl)); } catch {}
  } catch {
    // Keep showing cached data if available; show error only if nothing loaded
  } finally {
    fetching = false;
    ptr.classList.remove('show');
    render();
  }
}

function doRefresh() {
  ptr.classList.add('show');
  load(true);
}

// ── Pull-to-Refresh ───────────────────────────────────────────────────────────
let ty0 = 0, pulling = false;

feed.addEventListener('touchstart', e => {
  if (feed.scrollTop === 0) ty0 = e.touches[0].clientY;
}, { passive: true });

feed.addEventListener('touchmove', e => {
  if (!ty0) return;
  if (e.touches[0].clientY - ty0 > 64 && !fetching) {
    pulling = true;
    ptr.classList.add('show');
  }
}, { passive: true });

feed.addEventListener('touchend', () => {
  if (pulling && !fetching) { pulling = false; doRefresh(); }
  else { ty0 = 0; pulling = false; ptr.classList.remove('show'); }
});

// ── Boot ──────────────────────────────────────────────────────────────────────
applyTheme();
applyLang();
load();

// ── Push Notifications ────────────────────────────────────────────────────────
// Capacitor 6 does not fire the Cordova `deviceready` event. The plugin bridge
// is available as soon as the document is parsed, so we run on `load` and bail
// out cleanly on web (where Capacitor.Plugins.PushNotifications is undefined).
async function initPushNotifications() {
  const PushNotifications = window.Capacitor?.Plugins?.PushNotifications;
  if (!PushNotifications) return;

  try {
    const perm = await PushNotifications.requestPermissions();
    if (perm.receive !== 'granted') {
      console.warn('[GeoPulse] Push permission not granted:', perm.receive);
      return;
    }

    PushNotifications.addListener('registration', ({ value }) => {
      console.log('[GeoPulse] FCM token:', value);
    });

    PushNotifications.addListener('registrationError', err => {
      console.warn('[GeoPulse] Push registration error:', err.error);
    });

    PushNotifications.addListener('pushNotificationReceived', notification => {
      const msg = notification.title || notification.body || 'New update';
      showToast(msg);
    });

    PushNotifications.addListener('pushNotificationActionPerformed', () => {
      doRefresh();
    });

    await PushNotifications.register();
  } catch (err) {
    console.warn('[GeoPulse] Push setup failed:', err);
  }
}

if (document.readyState === 'complete' || document.readyState === 'interactive') {
  initPushNotifications();
} else {
  window.addEventListener('DOMContentLoaded', initPushNotifications, { once: true });
}

function showToast(msg) {
  const t = document.createElement('div');
  t.textContent = msg;
  Object.assign(t.style, {
    position:'fixed', bottom:'calc(24px + var(--sab))', left:'50%',
    transform:'translateX(-50%)', background:'var(--text)', color:'var(--bg)',
    padding:'10px 18px', borderRadius:'8px', fontSize:'13px',
    fontWeight:'600', zIndex:'999', whiteSpace:'nowrap',
    boxShadow:'0 4px 12px rgba(0,0,0,.25)',
  });
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 3500);
}
