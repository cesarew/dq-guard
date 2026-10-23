"""报告渲染：Markdown / HTML / JSON。

设计原则
--------
- **Markdown 优先**：能直接贴进 CI 日志、PR 评论、Confluence。
- **失败行给行号**：行号是文件行号（表头算第 1 行），可直接在 Excel 里跳转。
- **口径可见**：规则的 `note` 会原样输出——「指标降级必须可见」是这个工具的态度。
"""

from __future__ import annotations

import html
import json
from datetime import datetime
from typing import Any, Dict, List

from .engine import RuleResult, RunReport

_SEVERITY_BADGE = {"error": "🔴 error", "warn": "🟡 warn", "info": "🔵 info"}


def _status(r: RuleResult) -> str:
    if r.error:
        return "⚠️ 未执行"
    if r.passed:
        return "✅ 通过"
    return "❌ 失败"


def _fmt_ratio(r: RuleResult) -> str:
    if not r.checked:
        return "—"
    return f"{r.fail_ratio * 100:.2f}%"


# ---------------------------------------------------------------- Markdown


def render_markdown(report: RunReport, title: str = "数据质量报告") -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    errored = report.failed_errors
    warned = report.failed_warns

    lines: List[str] = []
    a = lines.append

    a(f"# {title}")
    a("")
    a(f"- 生成时间：{now}")
    a(f"- 数据源：`{report.source}`")
    a(f"- 规模：**{report.row_count}** 行 × **{report.column_count}** 列")
    a(f"- 规则：**{len(report.results)}** 条（通过 "
      f"{sum(1 for r in report.results if r.passed)} 条）")
    a("")

    verdict = "❌ **未通过**" if (errored or report.errors_in_rule_execution) else "✅ **通过**"
    a(f"## 结论：{verdict}")
    a("")
    if errored:
        a(f"失败规则（error 级）：{', '.join('`%s`' % r.rule_id for r in errored)}")
        a("")
    if warned:
        a(f"失败规则（warn 级）：{', '.join('`%s`' % r.rule_id for r in warned)}")
        a("")
    if report.errors_in_rule_execution:
        a(f"无法执行的规则：{', '.join('`%s`' % r.rule_id for r in report.errors_in_rule_execution)}")
        a("")

    a("## 规则明细")
    a("")
    a("| 规则 | 类型 | 级别 | 状态 | 检查 | 失败 | 失败率 |")
    a("|---|---|---|---|---|---|---|")
    for r in report.results:
        a(
            f"| `{r.rule_id}` | {r.rule_type} | {_SEVERITY_BADGE.get(r.severity, r.severity)} "
            f"| {_status(r)} | {r.checked} | {r.failed} | {_fmt_ratio(r)} |"
        )
    a("")

    failures = [r for r in report.results if not r.passed]
    if failures:
        a("## 失败详情")
        a("")
        for r in failures:
            a(f"### `{r.rule_id}`（{r.rule_type} / {r.severity}）")
            a("")
            if r.description:
                a(f"> {r.description}")
                a("")
            if r.error:
                a(f"**未能执行**：{r.error}")
                a("")
                continue
            if r.note:
                a(f"**口径说明**：{r.note}")
                a("")
            if r.failed_rows:
                shown = r.failed_rows[:20]
                more = len(r.failed_rows) - len(shown)
                row_text = ", ".join(str(n) for n in shown)
                if more > 0:
                    row_text += f" …等共 {len(r.failed_rows)} 行"
                a(f"**失败行号**（文件行号，表头为第 1 行）：{row_text}")
                a("")
            if r.samples:
                cols = list(r.samples[0].keys())
                a("| " + " | ".join(cols) + " |")
                a("|" + "---|" * len(cols))
                for s in r.samples:
                    a("| " + " | ".join(str(s.get(c, "")) for c in cols) + " |")
                a("")

    a("---")
    a("")
    a("由 [dq-guard](https://github.com/) 生成 —— 零依赖声明式数据质量检查。")
    a("")
    return "\n".join(lines)


# ---------------------------------------------------------------- HTML


def render_html(report: RunReport, title: str = "数据质量报告") -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ok = report.passed
    rows_html = []
    for r in report.results:
        cls = "ok" if r.passed else ("err" if r.severity == "error" else "warn")
        rows_html.append(
            f"<tr class='{cls}'><td><code>{html.escape(r.rule_id)}</code></td>"
            f"<td>{html.escape(r.rule_type)}</td>"
            f"<td>{html.escape(r.severity)}</td>"
            f"<td>{_status(r)}</td>"
            f"<td class='num'>{r.checked}</td>"
            f"<td class='num'>{r.failed}</td>"
            f"<td class='num'>{_fmt_ratio(r)}</td></tr>"
        )

    detail_html = []
    for r in report.results:
        if r.passed:
            continue
        body = ""
        if r.error:
            body = f"<p class='muted'>未能执行：{html.escape(r.error)}</p>"
        elif r.failed_rows:
            body = (
                "<p>失败行号：" +
                ", ".join(str(n) for n in r.failed_rows[:20]) +
                (f" …共 {len(r.failed_rows)} 行" if len(r.failed_rows) > 20 else "") +
                "</p>"
            )
        detail_html.append(
            f"<section><h3><code>{html.escape(r.rule_id)}</code> "
            f"<span class='badge {r.severity}'>{r.severity}</span></h3>"
            f"<p class='muted'>{html.escape(r.description)}</p>{body}</section>"
        )

    details = "\n".join(detail_html) or "<p class='muted'>所有规则均通过。</p>"

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>{html.escape(title)}</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font-family: -apple-system, "Segoe UI", "Noto Sans CJK SC", sans-serif;
         max-width: 980px; margin: 2rem auto; padding: 0 1rem; line-height: 1.6; }}
  h1 {{ font-size: 1.5rem; margin-bottom: .25rem; }}
  .meta {{ color: #777; font-size: .9rem; margin-bottom: 1.5rem; }}
  .verdict {{ font-size: 1.1rem; font-weight: 600; padding: .75rem 1rem;
              border-radius: 8px; margin: 1rem 0; }}
  .verdict.pass {{ background: #e7f6ec; color: #0f6b32; }}
  .verdict.fail {{ background: #fdeaea; color: #8c1c1c; }}
  table {{ border-collapse: collapse; width: 100%; font-size: .92rem; }}
  th, td {{ border-bottom: 1px solid #ddd; padding: .45rem .6rem; text-align: left; }}
  th {{ background: rgba(127,127,127,.08); }}
  td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  tr.err td {{ background: rgba(220,50,50,.07); }}
  tr.warn td {{ background: rgba(230,170,40,.10); }}
  section {{ border: 1px solid #ddd; border-radius: 8px; padding: .75rem 1rem; margin: .75rem 0; }}
  h3 {{ margin: .2rem 0 .5rem; font-size: 1rem; }}
  .muted {{ color: #777; }}
  .badge {{ font-size: .75rem; padding: .1rem .45rem; border-radius: 999px; color: #fff; }}
  .badge.error {{ background: #c0392b; }}
  .badge.warn {{ background: #c98a12; }}
  .badge.info {{ background: #2c6fb5; }}
</style></head>
<body>
  <h1>{html.escape(title)}</h1>
  <div class="meta">生成时间 {now} · 数据源 <code>{html.escape(report.source)}</code>
    · {report.row_count} 行 × {report.column_count} 列 · {len(report.results)} 条规则</div>
  <div class="verdict {'pass' if ok else 'fail'}">{'✅ 通过' if ok else '❌ 未通过'}</div>
  <table>
    <thead><tr><th>规则</th><th>类型</th><th>级别</th><th>状态</th>
      <th>检查</th><th>失败</th><th>失败率</th></tr></thead>
    <tbody>
      {''.join(rows_html)}
    </tbody>
  </table>
  <h2>失败详情</h2>
  {details}
</body></html>
"""


# ---------------------------------------------------------------- JSON


def render_json(report: RunReport) -> str:
    payload: Dict[str, Any] = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source": report.source,
        "row_count": report.row_count,
        "column_count": report.column_count,
        "passed": report.passed,
        "rules": [
            {
                "rule_id": r.rule_id,
                "rule_type": r.rule_type,
                "severity": r.severity,
                "passed": r.passed,
                "checked": r.checked,
                "failed": r.failed,
                "failed_rows": r.failed_rows,
                "error": r.error,
                "note": r.note,
            }
            for r in report.results
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


RENDERERS = {
    "markdown": render_markdown,
    "md": render_markdown,
    "html": render_html,
    "json": render_json,
}
