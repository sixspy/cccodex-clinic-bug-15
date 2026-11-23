# cc-clinic-lab · 临床试验访视采集台

数据工程产品线基线。题号前缀 `clinic-*`，默认端口 **7600**。

## 技术栈

- 后端：CherryPy + SQLite
- 前端：原生 JS SPA（顶栏薄荷绿丝带导航）
- 会话：itsdangerous 签名 Cookie
- 测试：pytest + httpx（依赖已列入 requirements）

## 登录

- 地址：`http://127.0.0.1:7600/login`
- 账号：`admin` / `123456`

## 页面

| 页面 | 能力 |
|------|------|
| 试验中心 | 中心登记、启停/观察、配额、方案版本生效 |
| 访视批次 | 开批、模拟抓取、追加访视行、合格入库、收齐/关闭 |
| 字段质控 | 按批/全量扫描、发现关闭/重开 |
| 缺口补采 | 排队、执行成功/失败、失败重试 |
| 访视对账 | 缺口/发现/补采对照、中心矩阵、审计 |
| 台参数 | 设置读写 |

## 主链

中心 → 访视批次抓取 → 质控发现 → 缺口补采 → 对账报告；设置与审计贯穿写操作。

## 本地

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pytest
python run.py
```

Docker：`docker compose up -d --build`，健康检查打 `/login`。

## 后续题面预留切口

- 访视行跨中心去重与冲突裁决
- 方案换版后存量批次字段兼容扫描
- 补采分片与并发上限
- 对账差异工单与导出
