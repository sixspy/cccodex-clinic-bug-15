export async function api(path, opts = {}) {
  const r = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...(opts.headers || {}) },
    credentials: 'same-origin',
    ...opts,
  });
  const text = await r.text();
  let data = {};
  try { data = text ? JSON.parse(text) : {}; } catch { data = { error: text }; }
  if (!r.ok) throw new Error(data.error || ('HTTP ' + r.status));
  return data;
}

export function chipClass(status) {
  const s = String(status || '');
  if (['启用', '合格', '已入库', '成功', '生效', '已关闭'].includes(s) && s !== '已关闭') {
    if (['启用', '合格', '已入库', '成功', '生效'].includes(s)) return 'ok';
  }
  if (['合格', '已入库', '成功', '生效', '启用'].includes(s)) return 'ok';
  if (['停用', '失败', '严重', '编码空', '废止'].includes(s)) return 'bad';
  if (['观察', '缺字段', '重复键', '待补采', '排队', '执行中', '开放', '草稿', '采集中'].includes(s)) return 'warn';
  return 'idle';
}

export function chip(status) {
  return `<span class="chip ${chipClass(status)}">${status || '-'}</span>`;
}

export function escapeHtml(s) {
  return String(s ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;');
}
