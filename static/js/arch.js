import { api, escapeHtml } from './api.js';

/**
 * 审计归档真实徽标：状态取自业务库（/api/audit_arch/dash），
 * 不再硬编码「归档已亮」。徽标与读轨键号对不上时显示红色假绿警示。
 */
export async function fetchArchStatus() {
  try {
    return await api('/api/audit_arch/dash');
  } catch {
    return null;
  }
}

export function archChip(dash) {
  if (!dash) return '<span class="chip idle">归档状态未知</span>';
  if (dash.aligned) {
    return `<span class="chip ok" title="读轨 ${escapeHtml(dash.active_read)} · 指纹 ${escapeHtml((dash.cutover_fp || '').slice(0, 16))}">${escapeHtml(dash.chip)}</span>`;
  }
  if (dash.chip === '归档已亮') {
    return `<span class="chip bad" title="徽标亮但读轨仍为 ${escapeHtml(dash.active_read)}">假绿·活审计可改</span>`;
  }
  return `<span class="chip warn" title="读轨 ${escapeHtml(dash.active_read)}">${escapeHtml(dash.chip)}</span>`;
}

export async function renderArchChipMount(el) {
  const mount = el.querySelector('[data-arch-chip]');
  if (!mount) return;
  const dash = await fetchArchStatus();
  mount.outerHTML = archChip(dash);
}
