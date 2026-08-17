# platform.deepseek.com 内部 API 调研笔记（2026-07 确认）

> 来源：平台前端 bundle（https://fe-static.deepseek.com/platform/static/main.*.js）静态分析
> 与社区项目（shajanjp/deepseek-usage、Shiorangerin/deepseek-usage-monitor、Leiuo/deepseek-monitor）。

## 认证

- 请求头：`Authorization: Bearer <userToken>`
- Token 来源：用户在 platform.deepseek.com 登录后，浏览器 localStorage 的 `userToken`
  键，值为 JSON：`JSON.parse(localStorage.getItem('userToken')).value`
- 建议附加头（社区项目验证有效）：
  - `x-app-version: 1.0.0`
  - `Origin: https://platform.deepseek.com`
  - `Referer: https://platform.deepseek.com/usage`
  - `User-Agent: <Chrome UA>`

## 响应外壳

```json
{ "code": 0, "msg": "", "data": { "biz_code": 0, "biz_msg": "", "biz_data": ... } }
```

## 端点（Base: https://platform.deepseek.com/api/v0）

| 端点 | 方法 | 参数 | 说明 |
|---|---|---|---|
| `/users/get_user_summary` | GET | - | 账户摘要：余额钱包、本月用量、总成本等 |
| `/users/get_api_keys` | GET | - | API Key 列表：`trackingId / name / sensitiveId` |
| `/usage/by_api_key/amount` | GET | `start, end, tz`（秒），可选 `api_key_tracking_ids` | 按 API Key×模型 的用量序列，`bucket` 粒度（3600=小时 / 86400=天） |
| `/usage/by_api_key/cost` | GET | `start, end, tz`（秒），可选 `api_key_tracking_ids` | 按币种×API Key×模型 的费用序列 |
| `/usage/export` | GET | `start, end, tz`（秒），可选 `api_key_tracking_id` | 返回 ZIP blob：`amount-*.csv` + `cost-*.csv`（官方原始导出） |

### 时间语义（平台前端确认）

- `start` = 起始日当地 00:00 换算成的 UTC 秒：`Date.UTC(y,m,d) / 1000 - tz`
- `end` = 结束日次日当地 00:00 的 UTC 秒（左闭右开）：`start(结束日) + 86400`
- `tz` = 时区偏移秒（如 UTC+8 → 28800）
- 平台 UI 日期跨度上限 30 天为**前端**限制（`2592e6` ms 校验）；服务端上限未确认，
  本工具统一按 ≤30 天窗口分片请求，避免触发服务端限制。

### amount 响应结构（biz_data）

```json
{
  "start": 0, "end": 0, "bucket": 3600,
  "models": ["deepseek-chat", ...],
  "series": [{
    "api_key": "<trackingId>",
    "model": "deepseek-chat",
    "buckets": [{
      "time": 1783000000,
      "usage": {
        "PROMPT_CACHE_HIT_TOKEN": 123,
        "PROMPT_CACHE_MISS_TOKEN": 456,
        "RESPONSE_TOKEN": 789,
        "REQUEST": 12
      }
    }]
  }]
}
```

### cost 响应结构（biz_data）

```json
{
  "start": 0, "end": 0, "bucket": 3600, "models": [...],
  "data": [{
    "currency": "CNY",
    "series": [{
      "api_key": "<trackingId>",
      "model": "deepseek-chat",
      "buckets": [{ "time": 1783000000, "cost": "0.012345" }]
    }]
  }]
}
```

## 官方导出 CSV（usage/export 返回的 zip 内）

- 文件名形如 `amount-2026-07-01_2026-08-01.csv` / `cost-*.csv`
- amount CSV 列（社区实测）：`utc_date, model, api_key_name, type, price, amount`
- type 取值：`input_cache_hit_tokens` / `input_cache_miss_tokens` / `output_tokens` / `request_count`
- `utc_date` 可能为 `YYYY-MM-DD` 或 `YYYYMMDD`（解析时需归一化）；粒度以实际文件为准（可能按日聚合）
- 解析器需按表头自适应，兼容多余/缺失列。

## 平台 UI 行为（用户痛点对应）

- 选择单日 → amount/cost 返回 `bucket=3600`（小时桶），前端按小时展示
- 多日范围（最长 30 天）→ 返回 `bucket=86400`（天桶）
- 导出按钮 → `usage/export` 下载 `usage_data_{start}_{end}.zip`

## 工具对策

1. **小时粒度**：逐日请求（24h 窗口）强制小时桶，跨天合并 → 任意长周期的小时明细。
2. **超长周期**：自动按 ≤30 天分片请求再合并。
3. **官方原始数据**：调用 usage/export 保留 zip 与 CSV，一并输出。
