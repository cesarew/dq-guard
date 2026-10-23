"""规则基类、数据集容器与注册表。

写一条新规则只需要三步：

1. 新建 `dq_guard/rules/<你的规则>.py`
2. 定义一个继承 `Rule` 的类，填 `type_name` 与 `required`，实现 `check()`
3. 用 `@register` 装饰，并在 `dq_guard/rules/__init__.py` 里 import 一次

约定
----
- **不做类型转换**：数据集里的值保持 CSV 原始字符串，需要数字时由规则自己转。
  这样「无法解析」和「值为空」可以被规则区分开，而不是在读取阶段就被悄悄吃掉。
- **行号是文件行号**：表头是第 1 行，第一条数据是第 2 行。报告里给的行号可以直接
  在 Excel / 编辑器里定位。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

#: 规则严重级别。`error` 会让整个检查以非零码退出，`warn`/`info` 只记录。
SEVERITIES = ("error", "warn", "info")


class RuleError(Exception):
    """规则构造或执行阶段的错误（配置写错、列不存在等）。"""


@dataclass
class Dataset:
    """读取后的数据集。值一律保持字符串原样。"""

    columns: List[str]
    rows: List[Dict[str, Any]]
    source: str = ""

    def row_no(self, index: int) -> int:
        """0 基下标 → 文件行号（表头占第 1 行）。"""
        return index + 2

    def has_column(self, name: str) -> bool:
        return name in self.columns

    def get(self, index: int, column: str) -> Any:
        return self.rows[index].get(column)


@dataclass
class RuleOutcome:
    """单条规则的执行结果。"""

    checked: int = 0
    #: 失败行的文件行号（升序）
    failed_rows: List[int] = field(default_factory=list)
    #: 失败行的样本证据，最多保留 samples 条
    samples: List[Dict[str, Any]] = field(default_factory=list)
    #: 规则的补充说明（例如「分母是全部仓位数，含禁用仓」这类口径声明）
    note: str = ""
    #: 规则无法执行时的原因；非空表示这条规则判为失败
    error: Optional[str] = None

    @property
    def failed(self) -> int:
        return len(self.failed_rows)

    #: 单条规则最多保留多少条证据样本
    max_samples: int = 5

    def add_failure(self, row_no: int, evidence: Dict[str, Any]) -> None:
        self.failed_rows.append(row_no)
        if len(self.samples) < self.max_samples:
            self.samples.append(evidence)


#: 规则类型名 → 规则类
RULES: Dict[str, type] = {}


def register(cls: type) -> type:
    """注册规则类的装饰器。"""
    type_name = getattr(cls, "type_name", "")
    if not type_name:
        raise RuleError(f"{cls.__name__} 缺少 type_name")
    if type_name in RULES:
        raise RuleError(f"规则类型 {type_name!r} 重复注册")
    RULES[type_name] = cls
    return cls


class Rule:
    """所有规则的基类。"""

    #: DSL 里 `type` 字段的取值
    type_name: str = ""
    #: 必须提供的参数名
    required: tuple = ()
    #: 人话说明，用于报告
    description: str = ""

    def __init__(self, spec: Dict[str, Any]):
        self.spec = spec
        self.rule_id = spec.get("id") or self.type_name
        self.severity = spec.get("severity", "error")
        self.description = spec.get("description") or self.description

        if self.severity not in SEVERITIES:
            raise RuleError(
                f"规则 {self.rule_id!r}: severity 必须是 {SEVERITIES} 之一，"
                f"实际是 {self.severity!r}"
            )
        missing = [k for k in self.required if k not in spec]
        if missing:
            raise RuleError(
                f"规则 {self.rule_id!r} ({self.type_name}) 缺少必需参数: "
                f"{', '.join(missing)}"
            )

    # ---- 给子类用的工具

    def require_column(self, ds: Dataset, column: str) -> None:
        if not ds.has_column(column):
            raise RuleError(
                f"规则 {self.rule_id!r}: 数据集没有列 {column!r}"
                f"（可用列: {', '.join(ds.columns)}）"
            )

    @staticmethod
    def is_missing(value: Any) -> bool:
        """空字符串、None、纯空白都算缺失。"""
        if value is None:
            return True
        return isinstance(value, str) and value.strip() == ""

    @staticmethod
    def to_number(value: Any) -> Optional[float]:
        """尽量转成数字；转不了返回 None（由调用方决定怎么判）。"""
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value).strip().replace(",", "")
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None

    def make_evidence(
        self, ds: Dataset, index: int, default_columns: List[str]
    ) -> Dict[str, Any]:
        """构造一条失败证据。

        规则可以在 DSL 里用 ``"evidence": ["station_id", "box_id"]`` 指定想看到的列；
        不指定则用 ``default_columns``。行号始终作为第一个字段出现，
        方便在 Excel 里直接定位。
        """
        columns = self.spec.get("evidence") or default_columns
        item: Dict[str, Any] = {"row": ds.row_no(index)}
        for col in columns:
            if ds.has_column(col):
                item[col] = ds.get(index, col)
        return item

    # ---- 子类必须实现

    def check(self, ds: Dataset) -> RuleOutcome:
        """执行检查并返回结果。"""
        raise NotImplementedError(f"{type(self).__name__}.check() 未实现")
