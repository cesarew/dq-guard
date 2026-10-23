"""unit_consistency —— 同一指标的多列口径/单位一致性。

要解决的真实问题
----------------
生产表里同一个指标常有「主字段 + 备用字段」，而两个字段的单位不一样。
典型例子（来自换电柜业务）：

- ``device.battery`` —— 设备总用电量，单位「度」
- ``box.quantity``   —— 仓位电量，单位「千分之一度」，通常要 ``/1000``

主字段偶尔全零（设备未上报），于是业务代码降级到备用字段；
如果降级时忘了乘系数，指标会差 1000 倍，而且**看起来完全正常**。

这条规则就是把「降级前的换算是否正确」变成可自动检查的东西。

DSL 参数
--------
```json
{ "id": "energy_unit_consistent", "type": "unit_consistency",
  "primary": "battery_kwh", "secondary": "quantity_raw",
  "factor": 0.001, "tolerance": 0.05 }
```

- ``primary``：主字段（必需）
- ``secondary``：备用字段（必需）
- ``factor``：约定的换算系数，满足 ``primary ≈ secondary * factor``（必需）
- ``tolerance``（默认 ``0.05``）：相对容差，
  ``|primary - secondary*factor| / max(|primary|, eps) <= tolerance`` 视为一致
- ``skip_when_primary_zero``（默认 ``true``）：主字段为 0 时跳过——
  这正是「降级场景」，此时无法比对，如实跳过而不是判失败

判定规则
--------
1. 两侧缺失 → 按 ``allow_blank``（默认 ``true``）跳过或判失败。
2. 主字段为 0 且 ``skip_when_primary_zero`` → 跳过，**但计入 skipped 计数**。
3. 超出容差 → 失败，``reason`` 同时给出两个原始值与换算后的期望值。
4. **全部跳过时必须在 ``note`` 里写「主字段全为 0，本规则未实际生效」**——
   静默跳过必须可见，否则规则形同不存在。
"""

from __future__ import annotations

from typing import Any, Dict

from ..base import Dataset, Rule, RuleError, RuleOutcome, register

#: 计算相对误差时的分母下限，避免主字段为 0 时除零
_EPS = 1e-12


@register
class UnitConsistencyRule(Rule):
    type_name = "unit_consistency"
    required = ("primary", "secondary", "factor")
    description = "同一指标的多字段在指定换算系数下是否一致（主字段为 0 时跳过）"

    def __init__(self, spec: Dict[str, Any]):
        super().__init__(spec)
        factor = spec.get("factor")
        if not isinstance(factor, (int, float)) or isinstance(factor, bool):
            raise RuleError(
                f"规则 {self.rule_id!r}: factor 必须是数字，实际是 {factor!r}"
            )
        if factor == 0:
            raise RuleError(f"规则 {self.rule_id!r}: factor 不能为 0")

        tolerance = spec.get("tolerance", 0.05)
        if not isinstance(tolerance, (int, float)) or isinstance(tolerance, bool):
            raise RuleError(
                f"规则 {self.rule_id!r}: tolerance 必须是数字，实际是 {tolerance!r}"
            )
        if tolerance < 0:
            raise RuleError(f"规则 {self.rule_id!r}: tolerance 不能为负")

    def check(self, ds: Dataset) -> RuleOutcome:
        primary = self.spec["primary"]
        secondary = self.spec["secondary"]
        factor = float(self.spec["factor"])
        tolerance = float(self.spec.get("tolerance", 0.05))
        skip_primary_zero = bool(self.spec.get("skip_when_primary_zero", True))
        allow_blank = bool(self.spec.get("allow_blank", True))

        self.require_column(ds, primary)
        self.require_column(ds, secondary)

        evidence_columns = [primary, secondary]
        outcome = RuleOutcome()

        skipped_primary_zero = 0
        skipped_blank = 0
        unparseable = 0

        for index, row in enumerate(ds.rows):
            raw_primary = row.get(primary)
            raw_secondary = row.get(secondary)

            if self.is_missing(raw_primary) or self.is_missing(raw_secondary):
                if allow_blank:
                    skipped_blank += 1
                    continue
                outcome.checked += 1
                evidence = self.make_evidence(ds, index, evidence_columns)
                evidence["reason"] = "任一字段缺失，无法比对"
                outcome.add_failure(ds.row_no(index), evidence)
                continue

            primary_value = self.to_number(raw_primary)
            secondary_value = self.to_number(raw_secondary)

            if primary_value is None or secondary_value is None:
                unparseable += 1
                outcome.checked += 1
                evidence = self.make_evidence(ds, index, evidence_columns)
                evidence["reason"] = (
                    f"无法解析为数字（{primary}={raw_primary!r}, "
                    f"{secondary}={raw_secondary!r}）"
                )
                outcome.add_failure(ds.row_no(index), evidence)
                continue

            if primary_value == 0 and skip_primary_zero:
                # 降级场景：主字段为 0 时无法比对，如实跳过并计数
                skipped_primary_zero += 1
                continue

            outcome.checked += 1
            expected = secondary_value * factor
            deviation = abs(primary_value - expected) / max(abs(primary_value), _EPS)

            if deviation > tolerance:
                evidence = self.make_evidence(ds, index, evidence_columns)
                evidence["expected"] = round(expected, 6)
                evidence["deviation"] = round(deviation, 6)
                evidence["reason"] = (
                    f"口径不一致：{primary}={primary_value:g}，"
                    f"按 {secondary}×{factor:g} 期望 {expected:g}，"
                    f"相对偏差 {deviation * 100:.2f}% > 容差 {tolerance * 100:.2f}%"
                )
                outcome.add_failure(ds.row_no(index), evidence)

        notes = []
        if skipped_primary_zero:
            notes.append(f"{skipped_primary_zero} 行因主字段为 0 被跳过（降级场景）")
        if skipped_blank:
            notes.append(f"{skipped_blank} 行因字段缺失被跳过")
        if unparseable:
            notes.append(f"{unparseable} 行取值无法解析为数字，已按失败计")

        total_rows = len(ds.rows)
        if total_rows and skipped_primary_zero == total_rows:
            notes.append("**主字段全为 0，本规则未实际生效**——请确认降级是否已发生")

        if notes:
            outcome.note = "；".join(notes)

        return outcome
