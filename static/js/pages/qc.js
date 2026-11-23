import { api, chip, escapeHtml } from '../api.js';
import { renderArchChipMount } from '../arch.js';

export async function renderQc(el) {
  const [findings, batches] = await Promise.all([
    api('/api/findings'),
    api('/api/batches'),
  ]);
  const summary = findings.summary || {};
  const openBatches = (batches.items || []).filter((b) => b.status !== '已关闭');

  el.innerHTML = `
    <div class="card">
      <h2><span data-arch-chip></span> 字段质控发现</h2>
      <p class="muted">对缺口质量行扫描生成发现；缺字段/编码空/重复键会带严重度。关闭发现不自动改质量，补采成功后会联动关闭。</p>
      <div class="grid">
        <div class="stat"><div class="n">${summary.open || 0}</div><div class="l">开放发现</div></div>
        <div class="stat"><div class="n">${summary.closed || 0}</div><div class="l">已关闭</div></div>
        <div class="stat"><div class="n">${(summary.by_severity && summary.by_severity['严重']) || 0}</div><div class="l">严重</div></div>
        <div class="stat"><div class="n">${(summary.by_severity && summary.by_severity['一般']) || 0}</div><div class="l">一般</div></div>
      </div>
      <div class="row">
        <select id="scanBatch">
          ${openBatches.map((b) => `<option value="${b.id}">${escapeHtml(b.batch_code + ' · ' + b.site_name)}</option>`).join('')}
        </select>
        <button id="scanOne">扫描选中批次</button>
        <button id="scanAll" class="warn">扫描全部开放批次</button>
        <select id="statusFilter">
          <option value="开放">仅开放</option>
          <option value="">全部状态</option>
          <option value="已关闭">仅已关闭</option>
        </select>
        <select id="sevFilter">
          <option value="">全部严重度</option>
          <option>提示</option>
          <option>一般</option>
          <option>严重</option>
        </select>
        <button id="reload" class="ghost">刷新</button>
      </div>
      <div id="msg" class="muted"></div>
    </div>
    <div class="card">
      <h2>发现列表</h2>
      <table>
        <thead>
          <tr>
            <th>ID</th><th>批次/中心</th><th>受试者访视</th><th>字段</th>
            <th>严重度</th><th>状态</th><th>说明</th><th>操作</th>
          </tr>
        </thead>
        <tbody id="body">
          ${(findings.items || []).map(rowHtml).join('') || '<tr><td colspan="8" class="muted">暂无发现</td></tr>'}
        </tbody>
      </table>
      <div class="card" style="margin-top:12px;box-shadow:none">
        <h2 style="font-size:15px">按字段汇总（开放）</h2>
        <div class="row">
          ${(summary.by_field || []).map((f) => `
            <span class="chip warn">${escapeHtml(f.field_name)} · ${f.c}</span>
          `).join('') || '<span class="muted">无</span>'}
        </div>
      </div>
    </div>`;

  function rowHtml(f) {
    return `
      <tr>
        <td>${f.id}</td>
        <td>${escapeHtml(f.batch_code)}<div class="muted">${escapeHtml(f.site_name || '')}</div></td>
        <td>${escapeHtml(f.subject_key)} / ${escapeHtml(f.visit_code)}<div>${chip(f.quality)}</div></td>
        <td>${escapeHtml(f.field_name)}</td>
        <td>${chip(f.severity)}</td>
        <td>${chip(f.status)}</td>
        <td class="muted">${escapeHtml(f.message || '')}</td>
        <td class="row">
          ${f.status === '开放'
            ? `<button data-close="${f.id}">关闭</button>`
            : `<button data-reopen="${f.id}" class="ghost">重开</button>`}
          <button data-view="${f.id}" class="ghost">详情</button>
        </td>
      </tr>`;
  }

  const msg = el.querySelector('#msg');
  const body = el.querySelector('#body');

  async function reload() {
    const status = el.querySelector('#statusFilter').value;
    const sev = el.querySelector('#sevFilter').value;
    const qs = new URLSearchParams();
    if (status) qs.set('status', status);
    if (sev) qs.set('severity', sev);
    const data = await api('/api/findings?' + qs.toString());
    body.innerHTML = (data.items || []).map(rowHtml).join('') || '<tr><td colspan="8" class="muted">暂无发现</td></tr>';
    bindRows();
  }

  function bindRows() {
    el.querySelectorAll('[data-close]').forEach((btn) => {
      btn.onclick = async () => {
        try {
          await api(`/api/findings/${btn.dataset.close}/close`, { method: 'POST', body: '{}' });
          await reload();
        } catch (e) { msg.textContent = e.message; msg.className = 'err'; }
      };
    });
    el.querySelectorAll('[data-reopen]').forEach((btn) => {
      btn.onclick = async () => {
        try {
          await api(`/api/findings/${btn.dataset.reopen}/reopen`, { method: 'POST', body: '{}' });
          await reload();
        } catch (e) { msg.textContent = e.message; msg.className = 'err'; }
      };
    });
    el.querySelectorAll('[data-view]').forEach((btn) => {
      btn.onclick = async () => {
        try {
          const f = await api(`/api/findings/${btn.dataset.view}`);
          msg.className = 'muted';
          msg.textContent = JSON.stringify({
            发现: f.id,
            字段: f.field_name,
            严重度: f.severity,
            状态: f.status,
            受试者: f.subject_key,
            访视: f.visit_code,
            载荷: f.payload,
            说明: f.message,
          }, null, 2);
        } catch (e) { msg.textContent = e.message; msg.className = 'err'; }
      };
    });
  }

  el.querySelector('#scanOne').onclick = async () => {
    try {
      const batchId = Number(el.querySelector('#scanBatch').value);
      const r = await api('/api/findings', {
        method: 'POST',
        body: JSON.stringify({ batch_id: batchId }),
      });
      msg.className = 'muted';
      msg.textContent = `扫描完成，新建 ${r.created} 条发现，当前开放合计 ${r.open_total}`;
      await reload();
    } catch (e) { msg.textContent = e.message; msg.className = 'err'; }
  };
  el.querySelector('#scanAll').onclick = async () => {
    try {
      const r = await api('/api/findings', {
        method: 'POST',
        body: JSON.stringify({ scan_all: true }),
      });
      msg.className = 'muted';
      msg.textContent = `全量扫描新建 ${r.created} 条`;
      await reload();
    } catch (e) { msg.textContent = e.message; msg.className = 'err'; }
  };
  el.querySelector('#reload').onclick = () => reload().catch((e) => { msg.textContent = e.message; msg.className = 'err'; });
  el.querySelector('#statusFilter').onchange = () => reload();
  el.querySelector('#sevFilter').onchange = () => reload();
  bindRows();
  await renderArchChipMount(el);
}
