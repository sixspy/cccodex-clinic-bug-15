import { api } from './api.js';
import { renderSites } from './pages/sites.js';
import { renderVisits } from './pages/visits.js';
import { renderQc } from './pages/qc.js';
import { renderBackfill } from './pages/backfill.js';
import { renderReconcile } from './pages/reconcile.js';
import { renderSettings } from './pages/settings.js';

const view = document.getElementById('view');
const pages = {
  sites: renderSites,
  visits: renderVisits,
  qc: renderQc,
  backfill: renderBackfill,
  reconcile: renderReconcile,
  settings: renderSettings,
};

async function refreshDash() {
  try {
    const d = await api('/api/dashboard');
    document.getElementById('dashHint').textContent =
      ` · 中心${d.sites} · 启用${d.sites_enabled} · 批次${d.batches} · 访视行${d.rows} · 缺口${d.gaps} · 开放发现${d.open_findings} · 补采中${d.pending_jobs}`;
  } catch (e) {
    if (String(e.message).includes('未登录')) location.href = '/login';
  }
}

async function go(name) {
  document.querySelectorAll('button.nav').forEach((b) => {
    b.classList.toggle('active', b.dataset.page === name);
  });
  view.innerHTML = '<p class="muted">加载中…</p>';
  try {
    await pages[name](view);
  } catch (e) {
    view.innerHTML = `<div class="card"><p class="err">${e.message}</p></div>`;
  }
  await refreshDash();
}

document.querySelectorAll('button.nav').forEach((b) => {
  b.onclick = () => go(b.dataset.page);
});
document.getElementById('logoutBtn').onclick = async () => {
  await api('/api/logout', { method: 'POST' });
  location.href = '/login';
};

go('sites');
