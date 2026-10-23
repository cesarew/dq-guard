"""cross_column —— 两列之间的比较约束。

典型用途
--------
- ``start_time <= end_time``
- ``used_capacity <= total_capacity``
- ``settlement_amount == order_amount``（对账）
- ``soc <= 100``（列与字面量比较）

DSL 参数
--------
```json
{ "id": "start_before_end", "type": "cross_column",
  "left": "start_time", "op": "<=", "right_column": "end_time" }
```

```json
{ "id": "soc_le_100", "type": "cross_column",
  "left": "soc", "op": "<=", "value": 100 }
```

- ``left``：左列名（必需）
- ``op``：``<`` ``<=`` ``==`` ``!=`` ``>=`` ``>`` 之一（必需）
- ``right_column`` 与 ``value``：**必须且只能给一个**
- ``allow_blank``（默认 ``true``）：任一侧缺失时跳过该行

比较语义
--------
两侧都能解析成数字时按**数值**比较（避免 ``"100" < "9"`` 这种字符串陷阱）；
否则 ``==``/``!=`` 退化为字符串比较，而其余操作符直接判失败并注明
「无法比较大小」——**宁可报错也不猜**，因为猜错会掩盖真实的数据问题。
"""

from __future__ import annotations

import operator
from typing import Any, Callable, Dict

from ..base import Dataset, Rule, RuleError, RuleOutcome, register

#: 操作符 → 比较函数
_COMPARATORS: Dict[str, Callable[[Any, Any], bool]] = {
    "<": operator.lt,
    "<=": operator.le,
    "==": operator.eq,
    "!=": operator.ne,
    ">=": operator.ge,
    ">": operator.gt,
}


@register
class CrossColumnRule(Rule):
    type_name = "cross_column"
    required = ("left", "op")
    description = "两列之间（或列与字面量）的比较约束，如 start_time <= end_time"

    def __init__(self, spec: Dict[str, Any]):
        super().__init__(spec)

        op = self.spec["op"]
        if op not in _COMPARATORS:
            raise RuleError(
                f"规则 {self.rule_id!r}: op 必须是 "
                f"{' '.join(_COMPARATORS)} 之一，实际是 {op!r}"
            )

        has_column = "right_column" in self.spec and self.spec["right_column"] is not None
        has_value = "value" in self.spec and self.spec["value"] is not None
        if has_column == has_value:
            raise RuleError(
                f"规则 {self.rule_id!r}: right_column 与 value 必须且只能提供一个"
            )

    def check(self, ds: Dataset) -> RuleOutcome:
        left = self.spec["left"]
        right_column = self.spec.get("right_column")
        literal = self.spec.get("value")
        op = self.spec["op"]
        allow_blank = bool(self.spec.get("allow_blank", True))
        compare = _COMPARATORS[op]

        self.require_column(ds, left)
        if right_column:
            self.require_column(ds, right_column)

        evidence_columns = [left] + ([right_column] if right_column else [])

        outcome = RuleOutcome()
        for index, row in enumerate(ds.rows):
            left_value = row.get(left)
            right_value = row.get(right_column) if right_column else literal

            if self.is_missing(left_value) or self.is_missing(right_value):
                if allow_blank:
                    continue
                outcome.checked += 1
                evidence = self.make_evidence(ds, index, evidence_columns)
                evidence["reason"] = "任一侧缺失，无法比较"
                outcome.add_failure(ds.row_no(index), evidence)
                continue

            outcome.checked += 1

            left_number = self.to_number(left_value)
            right_number = self.to_number(right_value)

            if left_number is not None and right_number is not None:
                ok = compare(left_number, right_number)
                shown = f"{left_number:g} {op} {right_number:g}"
            elif op in ("==", "!="):
                same = str(left_value).strip() == str(right_value).strip()
                ok = same if op == "==" else not same
                shown = f"{left_value!r} {op} {right_value!r}（非数值，按字符串比较）"
            else:
                ok = False
                shown = (
                    f"{left_value!r} {op} {right_value!r}"
                    "（至少一侧不是数字，无法比较大小）"
                )

            if not ok:
                evidence = self.make_evidence(ds, index, evidence_columns)
                evidence["reason"] = f"不满足 {shown}"
                outcome.add_failure(ds.row_no(index), evidence)

        return outcome
