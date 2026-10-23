"""funnel —— 漏斗不变量：各阶段产出不得多于投入。

为什么需要它
------------
数据管道最常见的静默失败是「某一步多产出了行」——去重后反而变多、过滤后行数
上涨，通常意味着关联把数据放大了（一对多 JOIN）或口径算错了。
把这条不变量写成规则，每次运行自动校验，比事后对数便宜得多。

DSL 参数
--------
数据源是一份**漏斗结果表**，每行一个阶段：

```csv
stage_order,stage_name,input_rows,output_rows
1,raw,150,150
2,dedup,150,147
3,quality,147,150      <- 这一行会被判失败
```

```json
{ "id": "funnel_monotonic", "type": "funnel",
  "input_column": "input_rows", "output_column": "output_rows", "strict": true }
```

- ``input_column``：投入列（默认 ``input_rows``）
- ``output_column``：产出列（默认 ``output_rows``）
- ``strict``（默认 ``true``）：为真时额外要求本行 ``input`` 等于上一行的
  ``output``（阶段首尾相接，中间不漏不重）；为假只校验单行内 ``output <= input``

判定规则
--------
1. 单行内 ``output > input`` → 失败，原因写「产出多于投入」。
2. ``strict`` 为真时，非首行且本行 ``input`` ≠ 上一行 ``output`` → 失败，
   原因同时给出两个数字。
3. 取值缺失或无法解析为数字 → 计为失败并在原因里说明
   （漏斗表是汇总表，解析不出来本身就是数据问题，不能静默跳过）。
"""

from __future__ import annotations

from typing import Optional

from ..base import Dataset, Rule, RuleOutcome, register


@register
class FunnelRule(Rule):
    type_name = "funnel"
    required = ()
    description = "漏斗不变量：各阶段产出不得多于投入，且阶段之间首尾相接"

    def check(self, ds: Dataset) -> RuleOutcome:
        input_column = self.spec.get("input_column", "input_rows")
        output_column = self.spec.get("output_column", "output_rows")
        strict = bool(self.spec.get("strict", True))

        self.require_column(ds, input_column)
        self.require_column(ds, output_column)

        evidence_columns = [input_column, output_column]
        name_column = self.spec.get("name_column")
        if name_column:
            evidence_columns = [name_column] + evidence_columns

        outcome = RuleOutcome()
        previous_output: Optional[float] = None
        broken_links = 0
        over_produced = 0

        for index, row in enumerate(ds.rows):
            raw_input = row.get(input_column)
            raw_output = row.get(output_column)
            in_number = self.to_number(raw_input)
            out_number = self.to_number(raw_output)

            outcome.checked += 1
            evidence = self.make_evidence(ds, index, evidence_columns)

            if in_number is None or out_number is None:
                evidence["reason"] = (
                    f"取值无法解析为数字（{input_column}={raw_input!r}, "
                    f"{output_column}={raw_output!r}）"
                )
                outcome.add_failure(ds.row_no(index), evidence)
                previous_output = None  # 断了，下一行不再校验衔接
                continue

            failed = False

            if out_number > in_number:
                over_produced += 1
                evidence["reason"] = (
                    f"产出多于投入：{out_number:g} > {in_number:g}"
                )
                outcome.add_failure(ds.row_no(index), evidence)
                failed = True

            if strict and previous_output is not None and in_number != previous_output:
                broken_links += 1
                suffix = (
                    f"阶段之间不衔接：本行投入 {in_number:g} "
                    f"≠ 上一行产出 {previous_output:g}"
                )
                if failed:
                    evidence["reason"] = f"{evidence['reason']}；{suffix}"
                else:
                    evidence = self.make_evidence(ds, index, evidence_columns)
                    evidence["reason"] = suffix
                    outcome.add_failure(ds.row_no(index), evidence)

            previous_output = out_number

        notes = []
        if over_produced:
            notes.append(f"{over_produced} 行产出多于投入")
        if broken_links:
            notes.append(f"{broken_links} 行与上一阶段不衔接")
        if notes:
            outcome.note = "；".join(notes)

        return outcome
