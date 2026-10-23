"""enum —— 取值属于白名单。

与 `not_null` 的配合：`enum` 默认把空值视为失败，所以「空值不合法」的场景
只写一条 `enum` 就够；如果某列允许为空，加 `"allow_blank": true`。
"""

from __future__ import annotations

from typing import Any, Dict, List

from ..base import Dataset, Rule, RuleError, RuleOutcome, register


@register
class EnumRule(Rule):
    type_name = "enum"
    required = ("column", "values")
    description = "指定列的取值必须属于给定的白名单"

    def __init__(self, spec: Dict[str, Any]):
        super().__init__(spec)
        values = self.spec.get("values")
        if not isinstance(values, (list, tuple)) or not values:
            raise RuleError(
                f"规则 {self.rule_id!r}: values 必须是非空数组，例如 [\"0\", \"1\", \"2\"]"
            )

    def check(self, ds: Dataset) -> RuleOutcome:
        column = self.spec["column"]
        self.require_column(ds, column)

        allowed: List[str] = [str(v).strip() for v in self.spec["values"]]
        allow_blank = bool(self.spec.get("allow_blank", False))

        outcome = RuleOutcome()
        for index, row in enumerate(ds.rows):
            value = row.get(column)

            if self.is_missing(value):
                if allow_blank:
                    continue
                outcome.checked += 1
                evidence = self.make_evidence(ds, index, [column])
                evidence["reason"] = "空值（enum 默认不允许为空）"
                outcome.add_failure(ds.row_no(index), evidence)
                continue

            outcome.checked += 1
            text = str(value).strip()
            if text not in allowed:
                evidence = self.make_evidence(ds, index, [column])
                evidence["reason"] = f"{text!r} 不在白名单 {allowed}"
                outcome.add_failure(ds.row_no(index), evidence)

        return outcome
