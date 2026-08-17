# DEVELOPMENT.md — 内部开发接续文档（仅供维护/开发使用）

> 本文档供**后续开发会话**快速接续：架构地图、数据流、约定、发布流程、已知问题与 TODO。
> 不是用户文档；用户文档见 README.md / README.en.md。

---

## 1. 项目是什么

DeepSeek 开放平台（platform.deepseek.com/usage）用量数据导出工具。
用户登录平台后，把浏览器 localStorage 里的 `userToken` 交给工具，即可：

- 按任意日期范围抓取**小时级/天级**用量（平台前端限制：小时仅单日可见、范围最多 30 天，本工具绕过）；
- 输出 **Excel / CSV / 报纸编辑风 HTML 图表报告 / 官方原始导出 CSV / meta.json**；
- CLI（`dsu`）与本地 Web 界面（Flask）双入口，多语言（zh/en）。

版本节奏：v1.0.1 → v1.0.5（每版必打 git tag，见 §7）。

## 2. 目录地图

```
ds-usage-export/
├── dsu.py                    # 入口：python dsu.py …（转 cli.main）
├── pyproject.toml            # 版本号 + dsu 命令注册
├── requirements.txt
├── 启动Web界面.bat / 一键导出.bat   # Windows 双击启动（纯 ASCII + CRLF，勿改编码！）
├── README.md / README.en.md  # 用户文档（中文/英文互链）
├── CHANGELOG.md              # 每版必更新
├── DEVELOPMENT.md            # 本文档
├── dsusage/
│   ├── __init__.py           # __version__（改版本必改这里）
│   ├── api.py                # 平台客户端：认证、by_api_key amount/cost、usage/export zip、summary、keys
│   ├── parsing.py            # 官方导出 CSV 解析（表头自适应、日期归一化、聚合）
│   ├── aggregate.py          # 把 UsageDataset 变成导出表（ExportTable：中文列名）
│   ├── exporters.py          # xlsx / csv / raw / meta.json 写出
│   ├── report.py             # 报纸风 HTML 报告：SVG 图表 + 悬停提示 + 动效 + 滚轮横滑 + 点击钉住
│   ├── service.py            # 编排：分片抓取、官方原始合并、调用 report
│   ├── cli.py                # argparse 子命令（login/check/keys/day/range/go/serve/diagnose/logout）
│   ├── webapp.py             # Flask：/api/check|keys|fetch|export|job|download|exports|save_token
│   ├── i18n.py               # 多语言字符串表（zh/en）与语言解析
│   ├── config.py             # token 存储 ~/.dsusage/config.json
│   ├── browser_token.py      # 可选：Playwright 自动提取 token
│   └── web/static/index.html # Web 界面（报纸风，内联 JS/CSS，EN/中文切换）
├── examples/report_demo.html / report_demo_en.html   # 合成数据示例报告
├── tests/                    # unittest：test_core / test_integration / test_report + fixtures.py
└── docs/
    ├── api-notes.md          # 平台内部 API 调研笔记（改 api.py 前必读）
    └── 获取Token.md          # 用户如何拿 token
```

## 3. 平台 API 要点（详细见 docs/api-notes.md）

- Base：`https://platform.deepseek.com/api/v0`，认证 `Authorization: Bearer <userToken>`
- token 来源：`JSON.parse(localStorage.getItem('userToken')).value`
- 关键端点：
  - `GET /usage/by_api_key/amount?start&end&tz` → 用量序列，`bucket`=3600(小时)/86400(天)
  - `GET /usage/by_api_key/cost?start&end&tz` → 费用序列（多币种）
  - `GET /usage/export?start&end&tz` → ZIP（amount-*.csv / cost-*.csv 官方原始）
  - `GET /users/get_user_summary`、`GET /users/get_api_keys`
- 时间语义：`start`=起始日当地 00:00 的 UTC 秒；`end`=结束日次日 00:00（左闭右开）；`tz`=时区偏移秒（UTC+8 → 28800）
- **坑**：cost/amount 响应的 `api_key` 可能是对象（`{tracking_id,...}`）——`api._norm_api_key()` 已归一化；改解析逻辑别回归。
- 平台错误码：`code=40003` = token 无效（`_parse_json` 已映射为 AuthError）。

## 4. 数据流

```
CLI/Web → Service.run_export(start,end,tz,granularity,...)
  → api.fetch_range          # auto: ≤30天分片；hourly: 逐日 24h 窗口（强制小时桶）
  → parse_amount / parse_cost + merge_cost_into_amount
  → UsageDataset             # series[buckets]，bucket_sec=3600/86400
  → aggregate.build_tables   # ExportTable 列表（中文列）
  → exporters.export_all     # xlsx + csv（utf-8-sig）+ raw + meta.json
  → report.build_report      # report.html（按 current_lang() 语言）
```

关键决策：
- 平台前端 30 天限制只在前端；本工具按 ≤30 天窗口分片（`iter_windows`），小时级逐日请求。
- 费用合并按 (time, api_key, model) 精确匹配；兜底按同时间同模型平均。
- 官方 CSV 解析按表头自适应，兼容 `YYYYMMDD` / `YYYY-MM-DD` / 带时间。

## 5. i18n 约定

- `i18n.py`：`_STRINGS`（zh/en 两个 dict）+ `COLUMNS_EN`（表格列名映射）+ `tr(lang,key,**fmt)` / `tr_col(lang,col)`。
- 语言解析顺序：显式 `--lang` > 配置文件 `lang` > 环境变量 `DSU_LANG` > 系统 locale > zh。
- **加字符串**：先加 key 到 zh 与 en 两张表，再在代码里 `tr(lang, key)`。
- CLI 内用 `current_lang()`；report 内函数带 `lang` 参数（缺省 current_lang()）；Web 前端用 `data-i18n` + `I18N` dict + `applyLang()`。
- Excel/CSV 表头保持中文（数据层产物）；HTML 报告与 Web 预览会翻译。

## 6. report.py 图表架构（本版本核心）

- 图表函数：`chart_bar` / `chart_stacked` / `chart_line` / `chart_donut` / `chart_hbar`，全部返回自包含 SVG 字符串。
- **多数据滚轮横滑**：数据点多时（bar/stacked >14、line >31）SVG 固定像素宽（`w = max(760, n*步长)`），容器 `.fig{overflow-x:auto}`，内联 JS 把 `wheel` 转成水平滚动。
- **悬停/钉住提示**：每个交互元素（柱/段/点/扇区/图例/条形）带 `data-tip`（纯文本，`\n` 换行）+ `<title>`（无 JS 兜底）；内联 JS 自绘 `.dsu-tip` 气泡，鼠标悬停显示、**点击钉住**（再点/Esc/点空白取消），初始化时移除 `<title>` 子节点避免双提示。
- 动效 CSS：`dsu-press/fade-up/grow-v/grow-h/draw/fade-in` + 悬停高亮。
- 刻度：`_ticks` 保证末档 ≥ 数据上界；`_fmt_full` 完整数字；`_fmt_num` 缩写（轴刻度用）。
- 布局防呆：pad_t=46 留标题区；柱顶数值标签只画在 `bh>20` 且有空间时；边缘标签向内锚定。

## 7. 发布流程（每次版本必做）

1. 改版本号：`dsusage/__init__.py`、`pyproject.toml`、`index.html`（masthead + footer1 两处 + I18N dict 的 footer1 zh/en）、两个 `.bat`、`tests/test_core.py::test_version`、README（标题+版本历史）、CHANGELOG。
2. 跑测试：`python -m unittest discover -s tests`（须全绿）。
3. 截图回归（若改 report/Web）：vision_html_screenshot + vision_glance 检查。
4. 同步 canonical：`D:\code\github_repository\ds-usage-export\`（排除 `exports/`、`__pycache__`）。
5. `git add -A && git commit && git push origin main`。
6. **打 tag**：`git tag <版本号> && git push origin <版本号>`（与既有风格一致：`1.0.1`…`1.0.5`，无 v 前缀）。
7. 向用户确认推送与 tag 结果。

## 8. 已知问题 / 风险

- **未用真实账号做全量回归**：小时桶/官方 CSV 的真实形态以用户反馈为准；`dsu diagnose` 可抓原始响应。
- 平台接口可能变更：token 存储键名、cost `api_key` 结构、CSV 列名均已做过兼容；再遇 500/解析异常先 `dsu diagnose`。
- 小时级逐日请求：N 天 ≈ 2N 次调用，长周期慢且可能触频控（已做退避重试）。
- Web 服务为 Flask 开发服务器，仅供本机；公网暴露有风险。
- Excel/CSV 表头未随语言翻译（有意为之）。
- Windows 控制台中文输出依赖 UTF-8 reconfigure；老 conhost 可能乱码（功能不受影响）。

## 9. 后续 TODO（按优先级）

- [ ] 真实账号验证后的校正：官方 CSV 是否小时粒度、`usage/export` 服务端上限确认。
- [ ] 导出 Excel 表头多语言（aggregate 增加列名 key 化）。
- [ ] Web 预览表头随语言已做；job 日志与文件分类徽标翻译。
- [ ] 长周期报告性能：万级点数图表分桶抽稀（聚合到小时/天再画）。
- [ ] 定时任务/增量导出（按天 append 到本地库，SQLite）。
- [ ] `--out` 目录覆盖保护 / 磁盘空间检查。
- [ ] 打包分发：PyInstaller 单文件 exe（用户无需 Python）。

## 10. 测试

- 纯合成数据（`tests/fixtures.py` 造平台响应），不依赖真实账号/网络。
- `test_core`：时间工具、解析、聚合、导出器、CLI 解析、api_key 对象兼容。
- `test_integration`：Flask 接口（假客户端）、CLI 全链路、下载路径防护、i18n 预览。
- `test_report`：报纸元素、tooltip/动效存在性、完整数字、英文报告、go 命令。
- 新增功能务必补测试；报告改动建议截图回归。
