import { api, chip, escapeHtml } from '../api.js';
import { renderArchChipMount } from '../arch.js';

/* audit_arch-board */
export async function renderReconcile(el) {
  const [dash, reports, matrix, audits] = await Promise.all([
    api('/api/dashboard'),
    api('/api/reports'),
    api('/api/reports/matrix'),
    api('/api/audits?limit=30'),
  ]);

  el.innerHTML = `
    <div class="card">
      <h2><span data-arch-chip></span> 访视对账台</h2>
      <p class="muted">对照缺口行、开放质控发现与补采队列，找出无发现缺口、陈旧发现、未覆盖补采等不一致。</p>
      <div class="grid">
        <div class="stat"><div class="n">${dash.gaps}</div><div class="l">当前缺口行</div></div>
        <div class="stat"><div class="n">${dash.open_findings}</div><div class="l">开放发现</div></div>
        <div class="stat"><div class="n">${dash.pending_jobs}</div><div class="l">待执行补采</div></div>
        <div class="stat"><div class="n">${dash.batches}</div><div class="l">批次数</div></div>
      </div>
      <div class="row">
        <button id="run">生成对账报告</button>
        <button id="reload" class="ghost">刷新</button>
      </div>
      <div id="latest" class="detail-box">尚未生成本次对账。</div>
    </div>
    <div class="card">
      <h2>中心缺口矩阵</h2>
      <table>
        <thead>
          <tr><th>中心</th><th>状态</th><th>批次</th><th>访视行</th><th>缺口</th><th>开放发现</th></tr>
        </thead>
        <tbody>
          ${(matrix.items || []).map((s) => `
            <tr>
              <td>${escapeHtml(s.site_code)} · ${escapeHtml(s.name)}</td>
              <td>${chip(s.status)}</td>
              <td>${s.batch_count}</td>
              <td>${s.row_count}</td>
              <td>${s.gap_count || 0}</td>
              <td>${s.open_findings || 0}</td>
            </tr>`).join('')}
        </tbody>
      </table>
    </div>
    <div class="card">
      <h2>历史对账报告</h2>
      <table>
        <thead><tr><th>ID</th><th>摘要</th><th>缺口</th><th>发现</th><th>补采中</th><th>不一致</th><th>时间</th></tr></thead>
        <tbody id="reportBody">
          ${(reports.items || []).map((r) => `
            <tr>
              <td>${r.id}</td>
              <td>${escapeHtml(r.summary)}</td>
              <td>${r.gap_rows}</td>
              <td>${r.open_findings}</td>
              <td>${r.pending_jobs}</td>
              <td>${chip(r.mismatch > 0 ? '有差异' : '对齐')}</td>
              <td class="muted">${escapeHtml(r.created_at || '')}</td>
            </tr>`).join('') || '<tr><td colspan="7" class="muted">暂无报告</td></tr>'}
        </tbody>
      </table>
    </div>
    <div class="card">
      <h2>最近审计</h2>
      <p class="muted">合计 ${audits.summary?.total || 0} 条。突变操作会写入审计轨迹。</p>
      <table>
        <thead><tr><th>时间</th><th>动作</th><th>实体</th><th>详情</th></tr></thead>
        <tbody>
          ${(audits.items || []).map((a) => `
            <tr>
              <td class="muted">${escapeHtml(a.created_at || '')}</td>
              <td>${escapeHtml(a.action)}</td>
              <td>${escapeHtml(a.entity_type)} #${a.entity_id}</td>
              <td>${escapeHtml(a.detail || '')}</td>
            </tr>`).join('')}
        </tbody>
      </table>
    </div>`;

  const latest = el.querySelector('#latest');
  el.querySelector('#run').onclick = async () => {
    try {
      const r = await api('/api/reports/run', { method: 'POST', body: '{}' });
      latest.textContent = JSON.stringify({
        摘要: r.summary,
        缺口行: r.gap_rows,
        开放发现: r.open_findings,
        待执行补采: r.pending_jobs,
        不一致分: r.mismatch,
        明细: r.detail,
      }, null, 2);
      const reports2 = await api('/api/reports');
      el.querySelector('#reportBody').innerHTML = (reports2.items || []).map((x) => `
        <tr>
          <td>${x.id}</td>
          <td>${escapeHtml(x.summary)}</td>
          <td>${x.gap_rows}</td>
          <td>${x.open_findings}</td>
          <td>${x.pending_jobs}</td>
          <td>${chip(x.mismatch > 0 ? '有差异' : '对齐')}</td>
          <td class="muted">${escapeHtml(x.created_at || '')}</td>
        </tr>`).join('');
    } catch (e) {
      latest.textContent = '错误：' + e.message;
    }
  };
  el.querySelector('#reload').onclick = () => renderReconcile(el);
  await renderArchChipMount(el);
}
