import { api, escapeHtml } from '../api.js';

export async function renderSettings(el) {
  const data = await api('/api/settings');
  const items = data.items || [];
  const snapshot = data.snapshot || {};

  el.innerHTML = `
    <div class="card">
      <h2>台参数</h2>
      <p class="muted">控制质控自动扫描开关、补采最大次数、配额告警与对账口径标签等。修改会写审计。</p>
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

  try {
    const dash = await api('/api/audit_arch/dash');
    el.innerHTML += `<div class="card" style="margin-top:1rem">
      <h3>归档钉定</h3>
      <span class="chip">${dash.chip}</span>
      <p class="muted">读轨 ${dash.active_read} · 切流指纹 ${dash.cutover_fp || '空'} · 拒回刷 ${dash.reject_refresh} · 归档 ${dash.archive_count} · 新旗 ${dash.live_flag || '空'} · 对齐差 ${dash.panel_pack_mismatch}</p>
      <div class="row">
        <button id="go_audit_arch" type="button">落台</button>
        <button id="half_audit_arch" type="button">半修对齐</button>
        <button id="cut_audit_arch" type="button">切流账册</button>
        <button id="dual_audit_arch" type="button">双写两轨</button>
      </div>
    </div>`;
    const go = el.querySelector('#go_audit_arch');
    if (go) go.onclick = async () => {
      await api('/api/audit_arch/commit', { method:'POST', body: JSON.stringify({ref:1}) });
      await renderSettings(el);
    };
    const half = el.querySelector('#half_audit_arch');
    if (half) half.onclick = async () => {
      await api('/api/audit_arch/half', { method:'POST', body:'{}' });
      await renderSettings(el);
    };
    const cut = el.querySelector('#cut_audit_arch');
    if (cut) cut.onclick = async () => {
      await api('/api/audit_arch/cutover', { method:'POST', body: JSON.stringify({ref_id:1, note:'审计归档'}) });
      await renderSettings(el);
    };
    const dual = el.querySelector('#dual_audit_arch');
    if (dual) dual.onclick = async () => {
      await api('/api/audit_arch/dual', { method:'POST', body: JSON.stringify({note:'审计归档'}) });
      await renderSettings(el);
    };
  } catch (e) { /* optional surface */ }

}
