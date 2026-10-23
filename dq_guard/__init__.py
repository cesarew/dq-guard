"""dq-guard — 零依赖的声明式数据质量检查工具。

设计目标
--------
1. **零运行时依赖**：只用标准库。规则配置原生支持 JSON，装 PyYAML 后可读 YAML。
2. **CI 友好**：检查失败返回非零退出码，报告可直接贴进 CI 日志。
3. **对中文业务数据友好**：内置经纬度颠倒、计量单位一致性等中文场景常见问题的规则位。

分层
----
    spec.py     规则 DSL 的解析与校验
    dataset.py  CSV/TSV 读取（保持原始字符串，不做隐式类型转换）
    base.py     Rule 基类与注册表
    rules/      各类规则的实现（部分为待实现的桩件，见文件内 TODO）
    engine.py   执行规则、汇总结果
    report.py   渲染 Markdown / HTML 报告
    cli.py      命令行入口
"""

from __future__ import annotations

__version__ = "0.1.0"

from .base import Dataset, Rule, RuleOutcome, RuleError  # noqa: E402,F401
from .engine import RuleResult, run_rules  # noqa: E402,F401
from .spec import ConfigError, load_config  # noqa: E402,F401

__all__ = [
    "__version__",
    "Dataset",
    "Rule",
    "RuleOutcome",
    "RuleError",
    "RuleResult",
    "run_rules",
    "load_config",
    "ConfigError",
]
