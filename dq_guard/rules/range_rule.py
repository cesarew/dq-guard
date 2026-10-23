"""range —— 数值落在区间内（含端点）。

设计要点
--------
- `min` / `max` 至少给一个。
- **空值默认跳过**（`allow_blank=True`）：空值的判定属于 `not_null` 的职责，
  两条规则各管一件事，组合使用比塞进一条规则更清楚。
- 给了值但**解析不出数字**时按失败计，并在 `note` 里如实标注有多少行是这种
  情况——这比静默跳过安全，因为「填了非数字」本身就是数据问题。
"""

from __future__ import annotations

from ..base import Dataset, Rule, RuleError, RuleOutcome, register


@register
class RangeRule(Rule):
    type_name = "range"
    required = ("column",)
    description = "指定列的数值必须落在 [min, max] 区间内（空值默认跳过）"

    def check(self, ds: Dataset) -> RuleOutcome:
        column = self.spec["column"]
        self.require_column(ds, column)

        low = self.spec.get("min")
        high = self.spec.get("max")
        if low is None and high is None:
            raise RuleError(
                f"规则 {self.rule_id!r}: range 至少需要 min 或 max 之一"
            )

        allow_blank = bool(self.spec.get("allow_blank", True))

        outcome = RuleOutcome()
        unparseable = 0

        for index, row in enumerate(ds.rows):
            value = row.get(column)

            if self.is_missing(value):
                if allow_blank:
                    continue
                outcome.checked += 1
                outcome.add_failure(
                    ds.row_no(index), self.make_evidence(ds, index, [column])
                )
                continue

            outcome.checked += 1
            number = self.to_number(value)

            if number is None:
                unparseable += 1
                evidence = self.make_evidence(ds, index, [column])
                evidence["reason"] = f"{value!r} 不是数字"
                outcome.add_failure(ds.row_no(index), evidence)
                continue

            if (low is not None and number < low) or (
                high is not None and number > high
            ):
                evidence = self.make_evidence(ds, index, [column])
                low_s = "-inf" if low is None else low
                high_s = "+inf" if high is None else high
                evidence["reason"] = f"{number} 不在 [{low_s}, {high_s}]"
                outcome.add_failure(ds.row_no(index), evidence)

        if unparseable:
            outcome.note = f"其中 {unparseable} 行取值无法解析为数字，已按失败计"
        return outcome
