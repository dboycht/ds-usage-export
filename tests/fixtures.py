"""共享测试工具：合成平台 API 响应。"""

from __future__ import annotations

from typing import Any, Dict, List


def biz_data(payload: Any) -> Dict[str, Any]:
    """包装成平台响应外壳。"""
    return {
        "code": 0,
        "msg": "ok",
        "data": {"biz_code": 0, "biz_msg": "", "biz_data": payload},
    }


def make_amount_biz(start: int, end: int, bucket: int,
                    series: List[Dict[str, Any]]) -> Dict[str, Any]:
    """构造 amount biz_data。series 项：{api_key, model, buckets:[{time, usage:{...}}]}"""
    return {
        "start": start,
        "end": end,
        "bucket": bucket,
        "models": sorted({s["model"] for s in series}),
        "series": series,
    }


def make_cost_biz(start: int, end: int, bucket: int, currency: str,
                  series: List[Dict[str, Any]]) -> Dict[str, Any]:
    """构造 cost biz_data。series 项：{api_key, model, buckets:[{time, cost}]}"""
    return {
        "start": start,
        "end": end,
        "bucket": bucket,
        "models": sorted({s["model"] for s in series}),
        "data": [{"currency": currency, "series": series}],
    }
