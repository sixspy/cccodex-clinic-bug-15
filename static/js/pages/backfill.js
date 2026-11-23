import { api, chip, escapeHtml } from '../api.js';
import { renderArchChipMount } from '../arch.js';

export async function renderBackfill(el) {
  const [jobs, gapRows] = await Promise.all([
    api('/api/jobs'),
    api('/api/rows?status=' + encodeURIComponent('待补采')),
  ]);
  const summary = jobs.summary || {};

  el.innerHTML = `
    <div class="card">
      <h2><span data-arch-chip></span> 缺口补采队列</h2>
      <p class="muted">对待补采/缺口访视行排队补采；执行成功会把载荷补齐、质量改合格并关闭关联质控发现。</p>
      <div class="grid">
        <div class="stat"><div class="n">${summary['排队'] || 0}</div><div class="l">排队</div></div>
        <div class="stat"><div class="n">${summary['执行中'] || 0}</div><div class="l">执行中</div></div>
        <div class="stat"><div class="n">${summary['成功'] || 0}</div><div class="l">成功</div></div>
        <div class="stat"><div class="n">${summary['失败'] || 0}</div><div class="l">失败</div></div>
      </div>
      <div class="row">
        <select id="statusFilter">
          <option value="">全部任务</option>
          <option>排队</option>
          <option>执行中</option>
          <option>成功</option>
          <option>失败</option>
        </select>
        <button id="reload" class="ghost">刷新</button>
      </div>
      <div id="msg" class="muted"></div>
    </div>
    <div class="card">
      <h2>待补采访视行（可一键排队）</h2>
      <table>
        <thead><tr><th>行ID</th><th>批次</th><th>中心</th><th>受试者访视</th><th>质量</th><th>操作</th></tr></thead>
        <tbody>
          ${(gapRows.items || []).map((r) => `
            <tr>
              <td>${r.id}</td>
              <td>${escapeHtml(r.batch_code)}</td>
              <td>${escapeHtml(r.site_name || '')}</td>
              <td>${escapeHtml(r.subject_key)} / ${escapeHtml(r.visit_code)}</td>
              <td>${chip(r.quality)}</td>
              <td><button data-enq="${r.id}">加入补采队列</button></td>
            </tr>`).join('') || '<tr><td colspan="6" class="muted">当前没有待补采行</td></tr>'}
        </tbody>
      </table>
    </div>
    <div class="card">
      <h2>补采任务</h2>
      <table>
        <thead>
          <tr>
            <th>任务号</th><th>行</th><th>中心批次</th><th>状态</th>
            <th>尝试</th><th>消息</th><th>操作</th>
          </tr>
        </thead>
        <tbody id="jobBody">
          ${(jobs.items || []).map(jobRow).join('') || '<tr><td colspan="7" class="muted">暂无任务</td></tr>'}
        </tbody>
      </table>
    </div>`;

  function jobRow(j) {
    return `
      <tr>
        <td>${escapeHtml(j.job_code)}</td>
        <td>#${j.row_id} ${escapeHtml(j.subject_key)}/${escapeHtml(j.visit_code)}</td>
        <td>${escapeHtml(j.site_name || '')}<div class="muted">${escapeHtml(j.batch_code || '')}</div></td>
        <td>${chip(j.status)}</td>
        <td>${j.attempt}</td>
        <td class="muted">${escapeHtml(j.message || '')}</td>
        <td class="row">
          ${j.status === '排队' || j.status === '失败' ? `<button data-run="${j.id}">执行成功</button>` : ''}
          ${j.status === '排队' ? `<button data-fail="${j.id}" class="danger">模拟失败</button>` : ''}
          ${j.status === '失败' ? `<button data-retry="${j.id}" class="warn">重试排队</button>` : ''}
          <button data-view="${j.id}" class="ghost">详情</button>
        </td>
      </tr>`;
  }

  const msg = el.querySelector('#msg');
  const jobBody = el.querySelector('#jobBody');

  async function reloadJobs() {
    const status = el.querySelector('#statusFilter').value;
    const url = status ? `/api/jobs?status=${encodeURIComponent(status)}` : '/api/jobs';
    const data = await api(url);
    jobBody.innerHTML = (data.items || []).map(jobRow).join('') || '<tr><td colspan="7" class="muted">暂无任务</td></tr>';
    bindJobs();
  }

  function bindJobs() {
    el.querySelectorAll('[data-run]').forEach((btn) => {
      btn.onclick = async () => {
        try {
          await api(`/api/jobs/${btn.dataset.run}/run`, {
            method: 'POST',
            body: JSON.stringify({ succeed: true }),
          });
          msg.className = 'muted';
          msg.textContent = `任务 ${btn.dataset.run} 执行成功`;
          await renderBackfill(el);
        } catch (e) { msg.textContent = e.message; msg.className = 'err'; }
      };
    });
    el.querySelectorAll('[data-fail]').forEach((btn) => {
      btn.onclick = async () => {
        try {
          await api(`/api/jobs/${btn.dataset.fail}/run`, {
            method: 'POST',
            body: JSON.stringify({ succeed: false }),
          });
          await renderBackfill(el);
        } catch (e) { msg.textContent = e.message; msg.className = 'err'; }
      };
    });
    el.querySelectorAll('[data-retry]').forEach((btn) => {
      btn.onclick = async () => {
        try {
          await api(`/api/jobs/${btn.dataset.retry}/retry`, { method: 'POST', body: '{}' });
          await renderBackfill(el);
        } catch (e) { msg.textContent = e.message; msg.className = 'err'; }
      };
    });
    el.querySelectorAll('[data-view]').forEach((btn) => {
      btn.onclick = async () => {
        try {
          const j = await api(`/api/jobs/${btn.dataset.view}`);
          msg.className = 'muted';
          msg.textContent = JSON.stringify(j, null, 2);
        } catch (e) { msg.textContent = e.message; msg.className = 'err'; }
      };
    });
  }

  el.querySelectorAll('[data-enq]').forEach((btn) => {
    btn.onclick = async () => {
      try {
        await api('/api/jobs', {
          method: 'POST',
          body: JSON.stringify({ row_id: Number(btn.dataset.enq) }),
        });
        await renderBackfill(el);
      } catch (e) { msg.textContent = e.message; msg.className = 'err'; }
    };
  });
  el.querySelector('#reload').onclick = () => reloadJobs().catch((e) => { msg.textContent = e.message; msg.className = 'err'; });
  el.querySelector('#statusFilter').onchange = () => reloadJobs();
  bindJobs();
  await renderArchChipMount(el);
}
