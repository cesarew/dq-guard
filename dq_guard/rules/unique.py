"""unique —— 列（或列组合）取值唯一。

语义：一个键出现超过一次时，**所有**出现该键的行都算失败（而不是只标记第二次
出现）。理由：数据质量问题里没有「谁是对的」这一说，把全部重复行标出来让人去
判定，比工具替人猜安全。
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Tuple

from ..base import Dataset, Rule, RuleError, RuleOutcome, register


@register
class UniqueRule(Rule):
    type_name = "unique"
    required = ("columns",)
    description = "指定列（或列组合）的取值必须唯一；重复键的所有行都会被标出"

    def __init__(self, spec: Dict[str, Any]):
        # 允许写成 "column": "box_id" 或 "columns": "box_id" 的简写
        normalized = dict(spec)
        if "columns" not in normalized and "column" in normalized:
            normalized["columns"] = [normalized.pop("column")]
        cols = normalized.get("columns")
        if isinstance(cols, str):
            normalized["columns"] = [cols]

        super().__init__(normalized)

        if not self.spec.get("columns"):
            raise RuleError(f"规则 {self.rule_id!r}: columns 不能为空")

    def check(self, ds: Dataset) -> RuleOutcome:
        columns: List[str] = list(self.spec["columns"])
        for col in columns:
            self.require_column(ds, col)

        ignore_blank = bool(self.spec.get("ignore_blank", False))

        # key -> 出现的行下标
        buckets: Dict[Tuple[Any, ...], List[int]] = defaultdict(list)
        for index, row in enumerate(ds.rows):
            key = tuple((row.get(c) or "").strip() if isinstance(row.get(c), str)
                        else row.get(c) for c in columns)
            if ignore_blank and all(self.is_missing(v) for v in key):
                continue
            buckets[key].append(index)

        outcome = RuleOutcome()
        outcome.checked = len(ds.rows)

        duplicates = {k: v for k, v in buckets.items() if len(v) > 1}
        for key, indexes in duplicates.items():
            for index in indexes:
                evidence = self.make_evidence(ds, index, columns)
                evidence["_key"] = " | ".join("" if v is None else str(v) for v in key)
                evidence["_dup_count"] = len(indexes)
                outcome.add_failure(ds.row_no(index), evidence)

        if duplicates:
            outcome.note = (
                f"共 {len(duplicates)} 个键重复，涉及 {outcome.failed} 行"
            )
        return outcome
