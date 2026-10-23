"""规则执行引擎：把 DSL 里的一串规则跑在数据集上，汇总成结果。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .base import RULES, Dataset, Rule, RuleError, RuleOutcome

# 触发所有规则的注册（import 副作用）
from . import rules as _rules  # noqa: F401


@dataclass
class RuleResult:
    rule_id: str
    rule_type: str
    severity: str
    description: str
    passed: bool
    checked: int = 0
    failed: int = 0
    failed_rows: List[int] = field(default_factory=list)
    samples: List[Dict[str, Any]] = field(default_factory=list)
    note: str = ""
    error: Optional[str] = None

    @property
    def fail_ratio(self) -> float:
        return (self.failed / self.checked) if self.checked else 0.0


@dataclass
class RunReport:
    results: List[RuleResult]
    row_count: int
    column_count: int
    source: str

    def by_severity(self, severity: str) -> List[RuleResult]:
        return [r for r in self.results if r.severity == severity and not r.passed]

    @property
    def failed_errors(self) -> List[RuleResult]:
        return self.by_severity("error")

    @property
    def failed_warns(self) -> List[RuleResult]:
        return self.by_severity("warn")

    @property
    def errors_in_rule_execution(self) -> List[RuleResult]:
        """规则本身跑不起来（列不存在等），无论 severity 都算失败。"""
        return [r for r in self.results if r.error]

    @property
    def passed(self) -> bool:
        return not self.failed_errors and not self.errors_in_rule_execution


def run_rules(dataset: Dataset, rule_specs: List[Dict[str, Any]]) -> RunReport:
    """依次执行规则。

    单条规则失败不会中断整体检查——**一次跑完所有规则再汇总**，
    这是数据质量工具的常规做法：修一次、看全部。
    """
    results: List[RuleResult] = []

    for spec in rule_specs:
        type_name = spec["type"]
        rule_cls = RULES.get(type_name)
        if rule_cls is None:
            known = ", ".join(sorted(RULES))
            results.append(
                RuleResult(
                    rule_id=spec.get("id", type_name),
                    rule_type=type_name,
                    severity=spec.get("severity", "error"),
                    description=spec.get("description", ""),
                    passed=False,
                    error=f"未知规则类型 {type_name!r}（已注册: {known}）",
                )
            )
            continue

        try:
            rule: Rule = rule_cls(spec)
        except RuleError as exc:
            results.append(
                RuleResult(
                    rule_id=spec.get("id", type_name),
                    rule_type=type_name,
                    severity=spec.get("severity", "error"),
                    description=spec.get("description", ""),
                    passed=False,
                    error=f"规则配置错误: {exc}",
                )
            )
            continue

        try:
            outcome: RuleOutcome = rule.check(dataset)
        except RuleError as exc:
            results.append(
                RuleResult(
                    rule_id=rule.rule_id,
                    rule_type=type_name,
                    severity=rule.severity,
                    description=rule.description,
                    passed=False,
                    error=str(exc),
                )
            )
            continue
        except NotImplementedError as exc:
            results.append(
                RuleResult(
                    rule_id=rule.rule_id,
                    rule_type=type_name,
                    severity=rule.severity,
                    description=rule.description,
                    passed=False,
                    error=f"该规则尚未实现: {exc}",
                )
            )
            continue

        results.append(
            RuleResult(
                rule_id=rule.rule_id,
                rule_type=type_name,
                severity=rule.severity,
                description=rule.description,
                passed=not outcome.failed_rows and not outcome.error,
                checked=outcome.checked,
                failed=outcome.failed,
                failed_rows=list(outcome.failed_rows),
                samples=list(outcome.samples),
                note=outcome.note,
                error=outcome.error,
            )
        )

    return RunReport(
        results=results,
        row_count=len(dataset.rows),
        column_count=len(dataset.columns),
        source=dataset.source,
    )
