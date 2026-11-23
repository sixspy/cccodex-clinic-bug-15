import { api, escapeHtml } from '../api.js';
import { archChip, fetchArchStatus } from '../arch.js';

async function renderArchPanel(el) {
  const dash = await fetchArchStatus();
  if (!dash) return;
  const fakeGreen = dash.chip === '归档已亮' && !dash.aligned;
  const sealed = !!dash.sealed;

  const rows = (dash.rows || []).filter((r) => !r.key.endsWith('_decoy'));
  const book = await api('/api/audit_arch/dash').then((d) => d.cutover || []).catch(() => []);

  el.innerHTML += `<div class="card" style="margin-top:1rem">
    <h3>审计归档钉定（甲路·旁路账册）</h3>
    <div class="row" style="align-items:center;gap:12px;flex-wrap:wrap">
      <div>参数页归档徽标：${archChip(dash)}</div>
      <div>邻页归档键号（读轨）：
        <span class="chip ${dash.active_read === 'cutover_book' ? 'ok' : 'warn'}">${escapeHtml(dash.active_read)}</span>
      </div>
      <div class="chip ${fakeGreen ? 'bad' : 'idle'}">徽标-键号${fakeGreen ? '对不上：挡活审计改写' : '一致'}</div>
    </div>
    ${fakeGreen ? '<p class="err">徽标亮着但读轨仍停旧归档键号，活审计改写已被闸口拦下（409）。请走甲路收口，或别再只修皮面。</p>' : ''}
    <p class="muted">
      切流指纹：<code>${escapeHtml((dash.cutover_fp || '空').slice(0, 32))}${dash.cutover_fp && dash.cutover_fp.length > 32 ? '…' : ''}</code>
      · 拒回刷：<b>${dash.reject_refresh ? '是' : '否'}</b>
      · 已收口：<b>${sealed ? '是' : '否'}</b>
      · 旁路账册条目：<b>${dash.archive_count}</b>
      · 新旗(乙路)：<b>${escapeHtml(dash.live_flag || '空')}</b>
    </p>
    <div class="row">
      <button id="cut_audit_arch" type="button" ${sealed ? 'disabled' : ''}>${sealed ? '已收口（禁重复）' : '甲路收口：封存账册并分叉读轨'}</button>
      <button id="half_audit_arch" type="button" class="warn" ${sealed ? 'disabled' : ''}>皮面半修（演示假绿被拦）</button>
      <button id="dual_audit_arch" type="button" class="ghost" title="本场禁双开">乙路双写（禁双开）</button>
      <button id="reload_arch" type="button" class="ghost">刷新归档态</button>
    </div>
    <div id="arch_msg" class="muted" style="margin-top:8px"></div>

    <h4 style="margin-top:14px">旁路账册（只读，收口后拒回刷）</h4>
    <table>
      <thead><tr><th>账册键</th><th>封存事件</th><th>行指纹</th></tr></thead>
      <tbody>
        ${book.length ? book.map((e) => `
          <tr>
            <td><code>${escapeHtml(e.key)}</code></td>
            <td class="muted">${escapeHtml(JSON.stringify(e.value))}</td>
            <td><code>${escapeHtml(e.fp || '')}</code></td>
          </tr>`).join('') : '<tr><td colspan="3" class="muted">尚未收口，账册为空</td></tr>'}
      </tbody>
    </table>

    <h4 style="margin-top:14px">钉定面全部键号（核对用）</h4>
    <div class="detail-box">${escapeHtml(JSON.stringify(rows, null, 2))}</div>
  </div>`;

  const msg = el.querySelector('#arch_msg');
  const show = (text, ok) => { msg.className = ok ? 'muted' : 'err'; msg.textContent = text; };

  el.querySelector('#reload_arch').onclick = () => renderSettings(el);
  const cut = el.querySelector('#cut_audit_arch');
  if (cut && !sealed) cut.onclick = async () => {
    try {
      const r = await api('/api/audit_arch/cutover', {
        method: 'POST',
        body: JSON.stringify({ ref_id: 1, note: '台参数页甲路收口' }),
      });
      show(`收口完成并即刻入库：读轨=${r.active_read} · 账册${r.book_count}条 · 拒回刷=${r.reject_refresh}`, true);
      await renderSettings(el);
    } catch (e) { show(e.message, false); }
  };
  const half = el.querySelector('#half_audit_arch');
  if (half && !sealed) half.onclick = async () => {
    try {
      await api('/api/audit_arch/half', { method: 'POST', body: '{}' });
      show('皮面已点亮但读轨仍旧轨——这是假绿，邻页活审计改写会被 409 拦下。', false);
      await renderSettings(el);
    } catch (e) { show(e.message, false); }
  };
  el.querySelector('#dual_audit_arch').onclick = async () => {
    try {
      await api('/api/audit_arch/dual', { method: 'POST', body: JSON.stringify({ note: '审计归档' }) });
    } catch (e) { show(`乙路已按禁双开拒绝：${e.message}`, false); }
  };
}

export async function renderSettings(el) {
  const data = await api('/api/settings');
  const items = data.items || [];
  const snapshot = data.snapshot || {};

  el.innerHTML = `
    <div class="card">
      <h2>台参数</h2>
      <p class="muted">控制质控自动扫描开关、补采最大次数、配额告警与对账口径标签等。修改会写审计；归档假绿期间这些活审计改写会被闸口拦下。</p>
      <div class="grid">
        <div class="stat"><div class="n">${snapshot.backfill_max_attempt || '-'}</div><div class="l">补采最大次数</div></div>
        <div class="stat"><div class="n">${snapshot.qc_auto_scan || '-'}</div><div class="l">自动质控</div></div>
        <div class="stat"><div class="n">${snapshot.site_quota_warn || '-'}</div><div class="l">配额告警阈值</div></div>
        <div class="stat"><div class="n">${escapeHtml((snapshot.clinic_timezone || '-').slice(0, 12))}</div><div class="l">时区</div></div>
      </div>
    </div>
    <div class="card">
      <table>
        <thead><tr><th>键</th><th>说明</th><th>当前值</th><th>新值</th><th>操作</th></tr></thead>
        <tbody>
          ${items.map((s) => `
            <tr>
              <td><code>${escapeHtml(s.key)}</code></td>
              <td>${escapeHtml(s.label)}</td>
              <td><strong>${escapeHtml(s.value)}</strong></td>
              <td><input data-key="${escapeHtml(s.key)}" value="${escapeHtml(s.value)}" /></td>
              <td><button data-save="${escapeHtml(s.key)}">保存</button></td>
            </tr>`).join('')}
        </tbody>
      </table>
      <div id="msg" class="muted" style="margin-top:10px"></div>
    </div>
    <div class="card">
      <h2>预留切口（后续题面）</h2>
      <ul class="muted">
        <li>访视行跨中心去重策略与冲突裁决面板</li>
        <li>方案换版后存量批次字段兼容扫描</li>
        <li>补采任务分片与并发上限</li>
        <li>对账报告导出与差异工单</li>
      </ul>
      <div class="detail-box">${escapeHtml(JSON.stringify(snapshot, null, 2))}</div>
    </div>`;

  const msg = el.querySelector('#msg');
  el.querySelectorAll('[data-save]').forEach((btn) => {
    btn.onclick = async () => {
      const key = btn.dataset.save;
      const input = el.querySelector(`input[data-key="${key}"]`);
      try {
        const updated = await api('/api/settings/update', {
          method: 'POST',
          body: JSON.stringify({ key, value: input.value }),
        });
        msg.className = 'muted';
        msg.textContent = `已保存 ${updated.key} = ${updated.value}`;
        await renderSettings(el);
      } catch (e) {
        msg.className = 'err';
        msg.textContent = e.message;
      }
    };
  });

  await renderArchPanel(el);
}
