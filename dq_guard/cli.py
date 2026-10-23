"""命令行入口。

    dq-guard examples/rules.json
    dq-guard examples/rules.json --format html --report reports/dq.html
    dq-guard --list-rules

退出码
------
    0  通过（或未触发 --fail-on 阈值）
    1  触发阈值（默认：任一 error 级规则失败）
    2  配置 / 数据 / 用法错误
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

from . import rules as _rules  # noqa: F401  触发规则注册
from .base import RULES, RuleError
from .dataset import load_dataset
from .engine import RunReport, run_rules
from .report import render_html, render_json, render_markdown
from .spec import ConfigError, load_config

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2

FORMATS = ("markdown", "md", "html", "json")
FAIL_ON = ("error", "warn", "info", "none")


def _write(stream, text: str) -> None:
    """按目标流的实际编码写出。

    Windows 控制台默认是 GBK，直接 print emoji（✅/❌）会抛 UnicodeEncodeError。
    这里先按流编码做一次 replace 往返，保证任何编码下都不会崩，
    报告文件本身始终以 UTF-8 写入，不受影响。
    """
    encoding = getattr(stream, "encoding", None) or "utf-8"
    try:
        safe = text.encode(encoding, errors="replace").decode(encoding, errors="replace")
    except LookupError:
        safe = text.encode("utf-8", errors="replace").decode("utf-8", errors="replace")
    stream.write(safe + "\n")


def _println(text: str = "") -> None:
    _write(sys.stdout, text)


def _eprintln(text: str = "") -> None:
    _write(sys.stderr, text)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="dq-guard",
        description="零依赖的声明式数据质量检查。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  dq-guard examples/rules.json\n"
            "  dq-guard examples/rules.json --format html --report out/dq.html\n"
            "  dq-guard examples/rules.json --fail-on warn\n"
            "  dq-guard --list-rules\n"
        ),
    )
    p.add_argument("config", nargs="?", help="规则配置文件（.json / .yaml）")
    p.add_argument(
        "--report",
        metavar="PATH",
        help="报告输出路径；不给则打印到标准输出（也覆盖配置里的 report.path）",
    )
    p.add_argument(
        "--format",
        choices=FORMATS,
        help="报告格式，覆盖配置里的 report.format",
    )
    p.add_argument(
        "--fail-on",
        choices=FAIL_ON,
        help="触发非零退出码的最低级别，覆盖配置里的 options.fail_on",
    )
    p.add_argument(
        "--samples",
        type=int,
        metavar="N",
        help="每条规则最多保留多少条证据样本，覆盖配置里的 report.samples",
    )
    p.add_argument(
        "--list-rules",
        action="store_true",
        help="列出所有已注册规则及其实现状态",
    )
    p.add_argument(
        "-q", "--quiet",
        action="store_true",
        help="只输出一行摘要（配合 --report 用于 CI）",
    )
    return p


def _list_rules() -> int:
    pending = set(getattr(_rules, "PENDING_RULES", ()))
    width = max(len(name) for name in RULES) if RULES else 10
    # 用 ASCII 标记而不是 emoji：--list-rules 的输出常被贴进文档/CI 日志
    _println(f"{'规则类型'.ljust(width)}  状态      说明")
    _println("-" * (width + 44))
    for name in sorted(RULES):
        state = "[TODO] 待实现" if name in pending else "[OK]   已实现"
        desc = RULES[name].description or ""
        _println(f"{name.ljust(width)}  {state}  {desc}")
    _println()
    _println(f"共 {len(RULES)} 条规则，其中 {len(RULES) - len(pending)} 条可用。")
    return EXIT_OK


def _resolve_exit_code(report: RunReport, fail_on: str) -> int:
    if fail_on == "none":
        return EXIT_OK
    # 规则跑不起来属于配置问题，任何阈值下都应报错
    if report.errors_in_rule_execution:
        return EXIT_FAILED
    if report.failed_errors:
        return EXIT_FAILED
    if fail_on in ("warn", "info") and report.failed_warns:
        return EXIT_FAILED
    if fail_on == "info" and any(not r.passed for r in report.results):
        return EXIT_FAILED
    return EXIT_OK


def _one_line_summary(report: RunReport) -> str:
    total = len(report.results)
    failed = sum(1 for r in report.results if not r.passed)
    state = "PASS" if report.passed else "FAIL"
    return (
        f"[{state}] {report.row_count} rows x {report.column_count} cols, "
        f"{total} rules, {failed} failed"
    )


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.list_rules:
        return _list_rules()
    if not args.config:
        parser.print_help()
        return EXIT_USAGE

    # ---- 配置
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        _eprintln(f"[配置错误] {exc}")
        return EXIT_USAGE

    # ---- 数据
    try:
        dataset = load_dataset(
            config.dataset.path,
            fmt=config.dataset.format,
            encoding=config.dataset.encoding,
            delimiter=config.dataset.delimiter,
        )
    except RuleError as exc:
        _eprintln(f"[数据错误] {exc}")
        return EXIT_USAGE

    # ---- 执行
    report = run_rules(dataset, config.rules)

    # ---- 渲染
    fmt = (args.format or config.report.format).lower()
    samples = args.samples if args.samples is not None else config.report.samples
    for result in report.results:
        if samples >= 0:
            result.samples = result.samples[:samples]

    if fmt == "json":
        text = render_json(report)
    elif fmt == "html":
        text = render_html(report, title=config.report.title)
    else:
        text = render_markdown(report, title=config.report.title)

    out_path = Path(args.report) if args.report else config.report.path
    if out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        # 报告文件统一 UTF-8，与控制台编码无关
        out_path.write_text(text, encoding="utf-8")
        if not args.quiet:
            _println(_one_line_summary(report))
        _println(f"报告已写入: {out_path}")
    else:
        if not args.quiet:
            _println(text)
        else:
            _println(_one_line_summary(report))

    fail_on = (args.fail_on or config.options.fail_on).lower()
    return _resolve_exit_code(report, fail_on)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
