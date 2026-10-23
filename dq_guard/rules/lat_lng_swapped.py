"""lat_lng_swapped —— 经纬度颠倒检测（中文业务场景常见问题）。

为什么这是「中文业务特有」
--------------------------
海外数据多以 GeoJSON / PostGIS 等规范格式流转，经纬度有明确的坐标参考系统；
而国内大量业务表是「一张 Excel 导出来的 CSV + 两个 float 列」，字段名写成
`lng` / `lat` 还是 `经度` / `纬度` 完全看开发，灌库时写反是高频事故。
本工具把「写反了」变成一个可自动检测的规则，而不是等地图打点打出海里去。

判定思路
--------
中国的经纬度范围是已知的：
- 纬度（lat）约 3.5 ~ 53.6
- 经度（lng）约 73.5 ~ 135.1

于是「纬度列里的值不在纬度范围内、却正好落在经度范围内」，
基本可以判定两列写反。反向同理。

DSL 参数
--------
```json
{ "id": "coords_not_swapped", "type": "lat_lng_swapped",
  "lat_column": "latitude", "lng_column": "longitude",
  "bounds": { "lat": [3.5, 53.6], "lng": [73.5, 135.1] } }
```

- ``lat_column`` / ``lng_column``：列名（必需）
- ``bounds``：可选，覆盖默认范围；默认即上面的中国范围
- ``allow_blank``（默认 ``true``）：任一侧缺失时跳过
- ``fix``（默认 ``false``）：为真时在 ``note`` 里给出修正建议汇总，
  **但不会改写数据**——本工具只出报告，不改数

判定条件（任一成立即判失败）
----------------------------
1. **两列互换**：``lat_column`` 的值落在**经度范围**内，且 ``lng_column`` 的值
   落在**纬度范围**内（注意不是"lat 不在纬度范围"——写反时 lng 列里装的是
   纬度值，它同样不在经度范围内，用那个条件永远抓不到）
2. **纬度为负**：``lat`` 为负数（中国纬度全为正）而 ``lng`` 为正数

> **报告文案必须保留「疑似」二字**：规则的失败是疑似而非确证
> （也可能只是坐标落在境外），避免业务方据此直接改数。
"""

from __future__ import annotations

from typing import Any, Dict, Tuple

from ..base import Dataset, Rule, RuleError, RuleOutcome, register

#: 默认判定范围（中国）
DEFAULT_BOUNDS: Dict[str, Tuple[float, float]] = {
    "lat": (3.5, 53.6),
    "lng": (73.5, 135.1),
}


@register
class LatLngSwappedRule(Rule):
    type_name = "lat_lng_swapped"
    required = ("lat_column", "lng_column")
    description = "检测经纬度两列是否写反（中国范围内判定，结论为疑似）"

    def __init__(self, spec: Dict[str, Any]):
        super().__init__(spec)
        bounds = self.spec.get("bounds") or {}
        if not isinstance(bounds, dict):
            raise RuleError(f"规则 {self.rule_id!r}: bounds 必须是对象")
        for key in ("lat", "lng"):
            if key in bounds:
                value = bounds[key]
                if (
                    not isinstance(value, (list, tuple))
                    or len(value) != 2
                    or value[0] > value[1]
                ):
                    raise RuleError(
                        f"规则 {self.rule_id!r}: bounds.{key} 必须是 "
                        f"[下界, 上界] 且下界≤上界，实际是 {value!r}"
                    )

    def check(self, ds: Dataset) -> RuleOutcome:
        lat_column = self.spec["lat_column"]
        lng_column = self.spec["lng_column"]
        self.require_column(ds, lat_column)
        self.require_column(ds, lng_column)

        bounds = self.spec.get("bounds") or {}
        lat_low, lat_high = bounds.get("lat", DEFAULT_BOUNDS["lat"])
        lng_low, lng_high = bounds.get("lng", DEFAULT_BOUNDS["lng"])

        allow_blank = bool(self.spec.get("allow_blank", True))
        give_fix = bool(self.spec.get("fix", False))

        evidence_columns = [lat_column, lng_column]
        outcome = RuleOutcome()
        swapped_rows = 0
        negative_lat_rows = 0

        for index, row in enumerate(ds.rows):
            raw_lat = row.get(lat_column)
            raw_lng = row.get(lng_column)

            if self.is_missing(raw_lat) or self.is_missing(raw_lng):
                if allow_blank:
                    continue
                outcome.checked += 1
                evidence = self.make_evidence(ds, index, evidence_columns)
                evidence["reason"] = "经纬度任一缺失，无法判定"
                outcome.add_failure(ds.row_no(index), evidence)
                continue

            lat = self.to_number(raw_lat)
            lng = self.to_number(raw_lng)
            outcome.checked += 1

            if lat is None or lng is None:
                evidence = self.make_evidence(ds, index, evidence_columns)
                evidence["reason"] = (
                    f"无法解析为数字（{lat_column}={raw_lat!r}, {lng_column}={raw_lng!r}）"
                )
                outcome.add_failure(ds.row_no(index), evidence)
                continue

            lat_in_range = lat_low <= lat <= lat_high
            lng_in_range = lng_low <= lng <= lng_high
            # 关键判定：纬度列里的值落在"经度范围"内，且经度列里的值落在"纬度范围"内。
            # 注意不能写成「lat 不在纬度范围 且 lng 在经度范围」——写反时
            # lng 列里装的是纬度值，它同样不在经度范围内，那个条件永远不成立。
            lat_looks_like_lng = lng_low <= lat <= lng_high
            lng_looks_like_lat = lat_low <= lng <= lat_high
            swapped = (
                (not lat_in_range)
                and (not lng_in_range)
                and lat_looks_like_lng
                and lng_looks_like_lat
            )

            reasons = []
            if swapped:
                swapped_rows += 1
                reasons.append(
                    f"疑似经纬度颠倒：{lat_column}={lat:g} 落在经度范围"
                    f"[{lng_low:g}, {lng_high:g}]，而 {lng_column}={lng:g} "
                    f"落在纬度范围[{lat_low:g}, {lat_high:g}]"
                )
            if lat < 0 and lng > 0:
                negative_lat_rows += 1
                reasons.append(
                    f"疑似经纬度颠倒：纬度为负（{lat:g}），而中国境内纬度应为正"
                )

            if reasons:
                evidence = self.make_evidence(ds, index, evidence_columns)
                evidence["reason"] = "；".join(reasons)
                if give_fix:
                    evidence["suggested_fix"] = {
                        lat_column: lng,
                        lng_column: lat,
                    }
                outcome.add_failure(ds.row_no(index), evidence)

        notes = []
        if swapped_rows:
            notes.append(f"{swapped_rows} 行疑似两列写反")
        if negative_lat_rows:
            notes.append(f"{negative_lat_rows} 行纬度为负")
        if notes:
            text = "；".join(notes) + "。以上为**疑似**，请确认坐标是否本就在境外"
            if give_fix:
                text += "；修正方式：交换两列"
            outcome.note = text

        return outcome
