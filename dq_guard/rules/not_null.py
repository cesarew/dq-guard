"""not_null —— 指定列不得缺失。

缺失的定义：``None``、空字符串、纯空白字符串。
无法区分「本该有值但没填」和「这一列本来就不适用」——如果需要这种区分，
请改用 ``enum`` 把允许的取值（含「不适用」）显式列出来。
"""

from __future__ import annotations

from ..base import Dataset, Rule, RuleOutcome, register


@register
class NotNullRule(Rule):
    type_name = "not_null"
    required = ("column",)
    description = "指定列不得为缺失值（空串、纯空白或 None）"

    def check(self, ds: Dataset) -> RuleOutcome:
        column = self.spec["column"]
        self.require_column(ds, column)

        outcome = RuleOutcome()
        for index, row in enumerate(ds.rows):
            outcome.checked += 1
            if self.is_missing(row.get(column)):
                outcome.add_failure(
                    ds.row_no(index),
                    self.make_evidence(ds, index, [column]),
                )
        return outcome
