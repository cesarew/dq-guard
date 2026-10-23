"""dq-guard 测试套件。

只用标准库 unittest，保证 `python -m unittest` 在零依赖环境下就能跑通。

    cd opensource/dq-guard
    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import io
import itertools
import json
import shutil
import tempfile  # noqa: F401  保留以说明我们刻意不用 TemporaryDirectory
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from dq_guard.cli import main as cli_main
from dq_guard.dataset import load_dataset
from dq_guard.engine import run_rules
from dq_guard.report import render_json, render_markdown
from dq_guard.rules import PENDING_RULES
from dq_guard.spec import ConfigError, load_config
from dq_guard.base import Dataset

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"

#: 临时目录放在仓库内，并**尽力删除**
#:
#: 不用 ``tempfile.TemporaryDirectory`` 的原因：它在退出时会 chmod 目录，
#: 在部分受限环境（沙箱、只读 %TEMP%）下会抛 PermissionError，
#: 把本来通过的测试标成 ERROR。这里改为自己建目录 + ``ignore_errors=True``，
#: 清理失败不影响测试结论。
_TMP_ROOT = ROOT / ".tmp_tests"
_TMP_ROOT.mkdir(exist_ok=True)
_counter = itertools.count(1)


def _safe_rmtree(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


def temp_dir(case: unittest.TestCase) -> Path:
    """为当前测试创建一个独立临时目录，结束后尽力清理。"""
    path = _TMP_ROOT / f"{case.__class__.__name__}_{case._testMethodName}_{next(_counter)}"
    path.mkdir(parents=True, exist_ok=True)
    case.addCleanup(_safe_rmtree, path)
    return path


def make_ds(rows, columns=None, source="<test>"):
    columns = columns or (list(rows[0].keys()) if rows else [])
    return Dataset(columns=columns, rows=rows, source=source)


def run_one(rule_spec, ds):
    report = run_rules(ds, [rule_spec])
    return report.results[0]


# ---------------------------------------------------------------- 数据集读取


class DatasetTests(unittest.TestCase):
    def test_load_example_csv(self):
        ds = load_dataset(EXAMPLES / "sample.csv")
        self.assertEqual(len(ds.rows), 8)
        self.assertEqual(len(ds.columns), 8)
        self.assertEqual(ds.columns[0], "station_id")
        # 值保持字符串原样，不做类型转换
        self.assertEqual(ds.rows[0]["soc"], "88")
        self.assertIsInstance(ds.rows[0]["soc"], str)

    def test_row_no_counts_header_as_line_one(self):
        ds = make_ds([{"a": "1"}], columns=["a"])
        self.assertEqual(ds.row_no(0), 2)

    def test_duplicate_header_is_deduped(self):
        tmp = temp_dir(self)
        p = tmp / "d.csv"
        p.write_text("a,a,a\n1,2,3\n", encoding="utf-8")
        ds = load_dataset(p)
        self.assertEqual(ds.columns, ["a", "a_2", "a_3"])

    def test_short_row_is_padded(self):
        tmp = temp_dir(self)
        p = tmp / "d.csv"
        p.write_text("a,b,c\n1\n", encoding="utf-8")
        ds = load_dataset(p)
        self.assertEqual(ds.rows[0], {"a": "1", "b": "", "c": ""})

    def test_empty_file_rejected(self):
        tmp = temp_dir(self)
        p = tmp / "empty.csv"
        p.write_text("", encoding="utf-8")
        from dq_guard.base import RuleError

        with self.assertRaises(RuleError):
            load_dataset(p)


# ---------------------------------------------------------------- not_null


class NotNullTests(unittest.TestCase):
    def test_flags_blank_and_whitespace(self):
        ds = make_ds([{"k": "x"}, {"k": ""}, {"k": "   "}, {}])
        result = run_one({"id": "nn", "type": "not_null", "column": "k"}, ds)
        self.assertFalse(result.passed)
        self.assertEqual(result.failed_rows, [3, 4, 5])

    def test_passes_when_all_present(self):
        ds = make_ds([{"k": "a"}, {"k": "b"}])
        result = run_one({"id": "nn", "type": "not_null", "column": "k"}, ds)
        self.assertTrue(result.passed)
        self.assertEqual(result.checked, 2)

    def test_missing_column_reports_error(self):
        ds = make_ds([{"k": "a"}])
        result = run_one({"id": "nn", "type": "not_null", "column": "nope"}, ds)
        self.assertFalse(result.passed)
        self.assertIsNotNone(result.error)


# ---------------------------------------------------------------- range


class RangeTests(unittest.TestCase):
    def test_out_of_range_and_boundaries(self):
        ds = make_ds([{"v": "0"}, {"v": "50"}, {"v": "100"}, {"v": "-1"}, {"v": "101"}])
        result = run_one(
            {"id": "r", "type": "range", "column": "v", "min": 0, "max": 100}, ds
        )
        self.assertEqual(result.failed_rows, [5, 6])  # 端点 0 / 100 合法

    def test_blank_skipped_by_default(self):
        ds = make_ds([{"v": "10"}, {"v": ""}])
        result = run_one(
            {"id": "r", "type": "range", "column": "v", "min": 0, "max": 100}, ds
        )
        self.assertTrue(result.passed)
        self.assertEqual(result.checked, 1)

    def test_blank_fails_when_allow_blank_false(self):
        ds = make_ds([{"v": ""}])
        result = run_one(
            {"id": "r", "type": "range", "column": "v", "min": 0,
             "allow_blank": False}, ds
        )
        self.assertFalse(result.passed)

    def test_unparseable_counted_as_failure(self):
        ds = make_ds([{"v": "abc"}, {"v": "5"}])
        result = run_one(
            {"id": "r", "type": "range", "column": "v", "min": 0, "max": 10}, ds
        )
        self.assertEqual(result.failed_rows, [2])
        self.assertIn("无法解析", result.note)

    def test_min_max_both_missing_is_config_error(self):
        ds = make_ds([{"v": "1"}])
        result = run_one({"id": "r", "type": "range", "column": "v"}, ds)
        self.assertFalse(result.passed)
        self.assertIsNotNone(result.error)


# ---------------------------------------------------------------- cross_column


class CrossColumnTests(unittest.TestCase):
    def test_numeric_comparison(self):
        ds = make_ds([
            {"start": "1", "end": "5"},
            {"start": "5", "end": "5"},   # 端点相等，<= 合法
            {"start": "9", "end": "5"},   # 倒挂，应失败
        ])
        result = run_one(
            {"id": "cc", "type": "cross_column", "left": "start",
             "op": "<=", "right_column": "end"}, ds
        )
        self.assertEqual(result.failed_rows, [4])

    def test_numeric_not_string_comparison(self):
        """"100" 与 "9" 必须按数值比，不能按字典序（否则 "100" < "9" 会为真）。"""
        ds = make_ds([{"a": "100", "b": "9"}])
        result = run_one(
            {"id": "cc", "type": "cross_column", "left": "a",
             "op": ">", "right_column": "b"}, ds
        )
        self.assertTrue(result.passed)

    def test_string_equality(self):
        ds = make_ds([{"a": "ok", "b": "ok"}, {"a": "ok", "b": "no"}])
        result = run_one(
            {"id": "cc", "type": "cross_column", "left": "a",
             "op": "==", "right_column": "b"}, ds
        )
        self.assertEqual(result.failed_rows, [3])

    def test_unparseable_with_ordering_op_fails(self):
        ds = make_ds([{"a": "abc", "b": "5"}])
        result = run_one(
            {"id": "cc", "type": "cross_column", "left": "a",
             "op": "<", "right_column": "b"}, ds
        )
        self.assertFalse(result.passed)
        self.assertIn("无法比较大小", result.samples[0]["reason"])

    def test_literal_value_form(self):
        ds = make_ds([{"soc": "80"}, {"soc": "150"}])
        result = run_one(
            {"id": "cc", "type": "cross_column", "left": "soc",
             "op": "<=", "value": 100}, ds
        )
        self.assertEqual(result.failed_rows, [3])

    def test_blank_skipped_by_default(self):
        ds = make_ds([{"a": "", "b": "5"}, {"a": "1", "b": "5"}])
        result = run_one(
            {"id": "cc", "type": "cross_column", "left": "a",
             "op": "<=", "right_column": "b"}, ds
        )
        self.assertTrue(result.passed)
        self.assertEqual(result.checked, 1)

    def test_blank_fails_when_disallowed(self):
        ds = make_ds([{"a": "", "b": "5"}])
        result = run_one(
            {"id": "cc", "type": "cross_column", "left": "a",
             "op": "<=", "right_column": "b", "allow_blank": False}, ds
        )
        self.assertFalse(result.passed)

    def test_bad_op_is_config_error(self):
        ds = make_ds([{"a": "1", "b": "2"}])
        result = run_one(
            {"id": "cc", "type": "cross_column", "left": "a",
             "op": "<=>", "right_column": "b"}, ds
        )
        self.assertIsNotNone(result.error)

    def test_both_operands_provided_is_config_error(self):
        ds = make_ds([{"a": "1", "b": "2"}])
        result = run_one(
            {"id": "cc", "type": "cross_column", "left": "a",
             "op": "<=", "right_column": "b", "value": 9}, ds
        )
        self.assertIsNotNone(result.error)

    def test_no_operand_is_config_error(self):
        ds = make_ds([{"a": "1"}])
        result = run_one(
            {"id": "cc", "type": "cross_column", "left": "a", "op": "<="}, ds
        )
        self.assertIsNotNone(result.error)


# ---------------------------------------------------------------- funnel


class FunnelTests(unittest.TestCase):
    def test_over_production_detected(self):
        ds = make_ds([
            {"input_rows": "147", "output_rows": "150"},  # 产出多于投入
        ])
        result = run_one(
            {"id": "f", "type": "funnel", "strict": False}, ds
        )
        self.assertEqual(result.failed_rows, [2])
        self.assertIn("产出多于投入", result.samples[0]["reason"])

    def test_strict_detects_broken_link(self):
        ds = make_ds([
            {"input_rows": "150", "output_rows": "147"},
            {"input_rows": "140", "output_rows": "140"},  # 投入 140 != 上行产出 147
        ])
        result = run_one({"id": "f", "type": "funnel", "strict": True}, ds)
        self.assertEqual(result.failed_rows, [3])
        self.assertIn("不衔接", result.samples[0]["reason"])

    def test_non_strict_ignores_link(self):
        ds = make_ds([
            {"input_rows": "150", "output_rows": "147"},
            {"input_rows": "140", "output_rows": "140"},
        ])
        result = run_one({"id": "f", "type": "funnel", "strict": False}, ds)
        self.assertTrue(result.passed)

    def test_healthy_funnel_passes(self):
        ds = make_ds([
            {"input_rows": "150", "output_rows": "150"},
            {"input_rows": "150", "output_rows": "147"},
            {"input_rows": "147", "output_rows": "147"},
        ])
        result = run_one({"id": "f", "type": "funnel"}, ds)
        self.assertTrue(result.passed)
        self.assertEqual(result.checked, 3)

    def test_unparseable_row_fails(self):
        ds = make_ds([{"input_rows": "abc", "output_rows": "10"}])
        result = run_one({"id": "f", "type": "funnel"}, ds)
        self.assertFalse(result.passed)
        self.assertIn("无法解析", result.samples[0]["reason"])

    def test_custom_column_names(self):
        ds = make_ds([{"in_n": "10", "out_n": "20"}])
        result = run_one(
            {"id": "f", "type": "funnel", "input_column": "in_n",
             "output_column": "out_n", "strict": False}, ds
        )
        self.assertFalse(result.passed)


# ---------------------------------------------------------------- lat_lng_swapped


class LatLngSwappedTests(unittest.TestCase):
    def test_swapped_columns_detected(self):
        """回归测试：写反时 lng 列里装的是纬度值，不能要求它落在经度范围内。"""
        ds = make_ds([
            {"lat": "39.9219", "lng": "116.4434"},   # 正常
            {"lat": "116.4434", "lng": "39.9219"},   # 写反
        ])
        result = run_one(
            {"id": "ll", "type": "lat_lng_swapped",
             "lat_column": "lat", "lng_column": "lng"}, ds
        )
        self.assertEqual(result.failed_rows, [3])
        self.assertIn("疑似经纬度颠倒", result.samples[0]["reason"])

    def test_out_of_range_but_not_swapped_is_ignored(self):
        """纯粹越界（如 999）不是写反，不归这条规则管（range 负责）。"""
        ds = make_ds([{"lat": "999", "lng": "999"}])
        result = run_one(
            {"id": "ll", "type": "lat_lng_swapped",
             "lat_column": "lat", "lng_column": "lng"}, ds
        )
        self.assertTrue(result.passed)

    def test_negative_latitude_detected(self):
        ds = make_ds([{"lat": "-33.9", "lng": "151.2"}])  # 悉尼，但纬度列是负
        result = run_one(
            {"id": "ll", "type": "lat_lng_swapped",
             "lat_column": "lat", "lng_column": "lng"}, ds
        )
        self.assertFalse(result.passed)
        self.assertIn("纬度为负", result.samples[0]["reason"])

    def test_custom_bounds(self):
        ds = make_ds([{"lat": "30.2", "lng": "120.1"}])  # 杭州
        # 默认中国范围下正常通过
        ok = run_one(
            {"id": "ll", "type": "lat_lng_swapped",
             "lat_column": "lat", "lng_column": "lng"}, ds
        )
        self.assertTrue(ok.passed)
        # 把范围收窄到北京，杭州就被判出来了（但这不是"写反"，是越界）
        narrow = run_one(
            {"id": "ll", "type": "lat_lng_swapped", "lat_column": "lat",
             "lng_column": "lng", "bounds": {"lat": [39, 41], "lng": [115, 117]}}, ds
        )
        self.assertTrue(narrow.passed)  # 仍不判为写反，因为两列都不像互换

    def test_blank_skipped(self):
        ds = make_ds([{"lat": "", "lng": "116.4"}, {"lat": "39.9", "lng": "116.4"}])
        result = run_one(
            {"id": "ll", "type": "lat_lng_swapped",
             "lat_column": "lat", "lng_column": "lng"}, ds
        )
        self.assertTrue(result.passed)
        self.assertEqual(result.checked, 1)

    def test_fix_suggestion(self):
        ds = make_ds([{"lat": "116.4434", "lng": "39.9219"}])
        result = run_one(
            {"id": "ll", "type": "lat_lng_swapped", "lat_column": "lat",
             "lng_column": "lng", "fix": True}, ds
        )
        self.assertFalse(result.passed)
        self.assertEqual(result.samples[0]["suggested_fix"],
                         {"lat": 39.9219, "lng": 116.4434})
        self.assertIn("交换两列", result.note)


# ---------------------------------------------------------------- unit_consistency


class UnitConsistencyTests(unittest.TestCase):
    def test_consistent_values_pass(self):
        ds = make_ds([
            {"kwh": "886.7", "raw": "886667.9"},
            {"kwh": "120.5", "raw": "120500"},
        ])
        result = run_one(
            {"id": "u", "type": "unit_consistency", "primary": "kwh",
             "secondary": "raw", "factor": 0.001}, ds
        )
        self.assertTrue(result.passed)
        self.assertEqual(result.checked, 2)

    def test_scale_mismatch_detected(self):
        """忘记乘系数会导致差 1000 倍——这是最典型的静默错误。"""
        ds = make_ds([{"kwh": "95.4", "raw": "954000"}])
        result = run_one(
            {"id": "u", "type": "unit_consistency", "primary": "kwh",
             "secondary": "raw", "factor": 0.001}, ds
        )
        self.assertEqual(result.failed_rows, [2])
        self.assertIn("口径不一致", result.samples[0]["reason"])
        self.assertEqual(result.samples[0]["expected"], 954.0)

    def test_primary_zero_skipped_and_visible(self):
        """全部跳过的规则必须自证「没实际生效」，否则形同不存在。"""
        ds = make_ds([{"kwh": "0", "raw": "150000"}, {"kwh": "0", "raw": "90000"}])
        result = run_one(
            {"id": "u", "type": "unit_consistency", "primary": "kwh",
             "secondary": "raw", "factor": 0.001}, ds
        )
        self.assertTrue(result.passed)
        self.assertEqual(result.checked, 0)
        self.assertIn("未实际生效", result.note)

    def test_tolerance_respected(self):
        ds = make_ds([{"kwh": "100", "raw": "102000"}])  # 偏差 2%
        loose = run_one(
            {"id": "u", "type": "unit_consistency", "primary": "kwh",
             "secondary": "raw", "factor": 0.001, "tolerance": 0.05}, ds
        )
        self.assertTrue(loose.passed)
        tight = run_one(
            {"id": "u", "type": "unit_consistency", "primary": "kwh",
             "secondary": "raw", "factor": 0.001, "tolerance": 0.01}, ds
        )
        self.assertFalse(tight.passed)

    def test_missing_factor_is_config_error(self):
        ds = make_ds([{"kwh": "1", "raw": "1000"}])
        result = run_one(
            {"id": "u", "type": "unit_consistency", "primary": "kwh",
             "secondary": "raw"}, ds
        )
        self.assertIsNotNone(result.error)

    def test_zero_factor_is_config_error(self):
        ds = make_ds([{"kwh": "1", "raw": "1000"}])
        result = run_one(
            {"id": "u", "type": "unit_consistency", "primary": "kwh",
             "secondary": "raw", "factor": 0}, ds
        )
        self.assertIsNotNone(result.error)


# ---------------------------------------------------------------- unique


class UniqueTests(unittest.TestCase):
    def test_all_duplicate_rows_are_flagged(self):
        ds = make_ds([{"k": "a"}, {"k": "b"}, {"k": "a"}, {"k": "a"}])
        result = run_one({"id": "u", "type": "unique", "columns": ["k"]}, ds)
        # 三行 a 全部标出（不替人判断哪一行才是对的）
        self.assertEqual(result.failed_rows, [2, 4, 5])
        self.assertEqual(result.checked, 4)

    def test_composite_key(self):
        ds = make_ds([
            {"a": "1", "b": "1"},
            {"a": "1", "b": "2"},
            {"a": "1", "b": "1"},
        ])
        result = run_one({"id": "u", "type": "unique", "columns": ["a", "b"]}, ds)
        self.assertEqual(result.failed_rows, [2, 4])

    def test_single_column_shorthand(self):
        """`column` 单数写法也应被接受。"""
        ds = make_ds([{"k": "a"}, {"k": "a"}])
        result = run_one({"id": "u", "type": "unique", "column": "k"}, ds)
        self.assertEqual(result.failed_rows, [2, 3])

    def test_passes_when_unique(self):
        ds = make_ds([{"k": "a"}, {"k": "b"}])
        result = run_one({"id": "u", "type": "unique", "columns": ["k"]}, ds)
        self.assertTrue(result.passed)


# ---------------------------------------------------------------- enum


class EnumTests(unittest.TestCase):
    def test_outside_whitelist(self):
        ds = make_ds([{"s": "0"}, {"s": "9"}])
        result = run_one(
            {"id": "e", "type": "enum", "column": "s", "values": ["0", "1", "2"]}, ds
        )
        self.assertEqual(result.failed_rows, [3])

    def test_blank_fails_by_default(self):
        ds = make_ds([{"s": ""}])
        result = run_one(
            {"id": "e", "type": "enum", "column": "s", "values": ["0"]}, ds
        )
        self.assertFalse(result.passed)

    def test_blank_allowed_when_switch_on(self):
        ds = make_ds([{"s": ""}])
        result = run_one(
            {"id": "e", "type": "enum", "column": "s", "values": ["0"],
             "allow_blank": True}, ds
        )
        self.assertTrue(result.passed)

    def test_empty_values_is_config_error(self):
        ds = make_ds([{"s": "0"}])
        result = run_one({"id": "e", "type": "enum", "column": "s", "values": []}, ds)
        self.assertIsNotNone(result.error)


# ---------------------------------------------------------------- 引擎


class EngineTests(unittest.TestCase):
    def test_unknown_rule_type_reports_error(self):
        ds = make_ds([{"k": "a"}])
        result = run_one({"id": "x", "type": "no_such_rule"}, ds)
        self.assertFalse(result.passed)
        self.assertIn("未知规则类型", result.error)

    def test_unimplemented_rule_reports_error_not_crash(self):
        """未实现的规则应被记为「未执行」，而不是让整个检查崩掉。"""
        from dq_guard.base import RULES, Rule, register

        class _NotReady(Rule):
            type_name = "_test_not_ready"
            description = "test stub"

            def check(self, ds):
                raise NotImplementedError("not ready yet")

        register(_NotReady)
        self.addCleanup(RULES.pop, "_test_not_ready", None)

        ds = make_ds([{"k": "a"}])
        result = run_one({"id": "stub", "type": "_test_not_ready"}, ds)
        self.assertFalse(result.passed)
        self.assertIn("尚未实现", result.error)

    def test_one_failing_rule_does_not_stop_others(self):
        ds = make_ds([{"a": "", "b": "1"}])
        report = run_rules(ds, [
            {"id": "r1", "type": "not_null", "column": "a"},
            {"id": "r2", "type": "not_null", "column": "b"},
        ])
        self.assertEqual(len(report.results), 2)
        self.assertFalse(report.results[0].passed)
        self.assertTrue(report.results[1].passed)

    def test_warn_failure_does_not_break_overall_pass(self):
        ds = make_ds([{"s": "9"}])
        report = run_rules(ds, [
            {"id": "e", "type": "enum", "column": "s",
             "values": ["0"], "severity": "warn"},
        ])
        self.assertTrue(report.passed)          # warn 不影响整体结论
        self.assertEqual(len(report.failed_warns), 1)


# ---------------------------------------------------------------- 配置


class SpecTests(unittest.TestCase):
    def _write_config(self, case, payload):
        tmp = temp_dir(case)
        (tmp / "sample.csv").write_text("a\n1\n", encoding="utf-8")
        p = tmp / "rules.json"
        p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return p

    @staticmethod
    def _base():
        return {
            "version": 1,
            "dataset": {"path": "sample.csv"},
            "rules": [{"id": "r", "type": "not_null", "column": "a"}],
        }

    def test_loads_example_config(self):
        cfg = load_config(EXAMPLES / "rules.json")
        self.assertEqual(len(cfg.rules), 8)
        self.assertTrue(cfg.dataset.path.exists())

    def test_relative_dataset_path_resolves_against_config_dir(self):
        cfg = load_config(EXAMPLES / "rules.json")
        self.assertEqual(cfg.dataset.path.parent, EXAMPLES)

    def test_missing_rules_rejected(self):
        payload = self._base()
        payload["rules"] = []
        with self.assertRaises(ConfigError):
            load_config(self._write_config(self, payload))

    def test_duplicate_rule_id_rejected(self):
        payload = self._base()
        payload["rules"] = [
            {"id": "same", "type": "not_null", "column": "a"},
            {"id": "same", "type": "not_null", "column": "a"},
        ]
        with self.assertRaises(ConfigError):
            load_config(self._write_config(self, payload))

    def test_bad_version_rejected(self):
        payload = self._base()
        payload["version"] = 99
        with self.assertRaises(ConfigError):
            load_config(self._write_config(self, payload))

    def test_bad_fail_on_rejected(self):
        payload = self._base()
        payload["options"] = {"fail_on": "sometimes"}
        with self.assertRaises(ConfigError):
            load_config(self._write_config(self, payload))

    def test_missing_dataset_file_rejected(self):
        payload = self._base()
        payload["dataset"] = {"path": "not-there.csv"}
        with self.assertRaises(ConfigError):
            load_config(self._write_config(self, payload))


# ---------------------------------------------------------------- 报告


class ReportTests(unittest.TestCase):
    def _report(self):
        ds = make_ds([{"k": ""}, {"k": "ok"}])
        return run_rules(ds, [
            {"id": "nn", "type": "not_null", "column": "k", "severity": "error"},
        ])

    def test_markdown_contains_verdict_and_row_numbers(self):
        text = render_markdown(self._report())
        self.assertIn("未通过", text)
        self.assertIn("失败行号", text)
        self.assertIn("`nn`", text)

    def test_json_is_valid_and_has_failed_rows(self):
        payload = json.loads(render_json(self._report()))
        self.assertFalse(payload["passed"])
        self.assertEqual(payload["rules"][0]["failed_rows"], [2])


# ---------------------------------------------------------------- CLI


class CliTests(unittest.TestCase):
    def _run(self, argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cli_main(argv)
        return code, buf.getvalue()

    def test_example_fails_with_exit_code_1(self):
        code, out = self._run([str(EXAMPLES / "rules.json"), "--quiet"])
        self.assertEqual(code, 1)
        self.assertIn("FAIL", out)

    def test_fail_on_none_always_exits_zero(self):
        code, _ = self._run(
            [str(EXAMPLES / "rules.json"), "--quiet", "--fail-on", "none"]
        )
        self.assertEqual(code, 0)

    def test_funnel_example_detects_over_production(self):
        """漏斗示例：第 3 阶段产出多于投入，必须被抓出来。"""
        out_path = temp_dir(self) / "f.md"
        code, _ = self._run([
            str(EXAMPLES / "rules_funnel.json"),
            "--quiet",
            "--report", str(out_path),
        ])
        self.assertEqual(code, 1)
        text = out_path.read_text(encoding="utf-8")
        self.assertIn("funnel_monotonic", text)
        self.assertIn("产出多于投入", text)

    def test_energy_example_detects_scale_mismatch(self):
        """单位一致性示例：D005 差了 1000 倍。"""
        out_path = temp_dir(self) / "e.md"
        code, _ = self._run([
            str(EXAMPLES / "rules_energy.json"),
            "--quiet",
            "--report", str(out_path),
        ])
        self.assertEqual(code, 1)
        text = out_path.read_text(encoding="utf-8")
        self.assertIn("energy_unit_consistent", text)
        self.assertIn("口径不一致", text)
        self.assertIn("D005", text)

    def test_list_rules(self):
        code, out = self._run(["--list-rules"])
        self.assertEqual(code, 0)
        self.assertIn("not_null", out)
        self.assertIn("lat_lng_swapped", out)
        self.assertIn("已实现", out)

    def test_missing_config_returns_usage_error(self):
        code, _ = self._run(["definitely-not-here.json"])
        self.assertEqual(code, 2)

    def test_broken_config_returns_usage_error(self):
        p = temp_dir(self) / "bad.json"
        p.write_text("{ not json", encoding="utf-8")
        code, _ = self._run([str(p)])
        self.assertEqual(code, 2)

    def test_report_file_written_and_html_supported(self):
        out_path = temp_dir(self) / "sub" / "r.html"
        code, _ = self._run([
            str(EXAMPLES / "rules.json"),
            "--quiet",
            "--format", "html",
            "--report", str(out_path),
        ])
        self.assertEqual(code, 1)
        self.assertTrue(out_path.exists())
        self.assertIn("<!DOCTYPE html>", out_path.read_text(encoding="utf-8"))

    def test_json_format_output(self):
        out_path = temp_dir(self) / "r.json"
        code, _ = self._run([
            str(EXAMPLES / "rules.json"),
            "--quiet",
            "--format", "json",
            "--report", str(out_path),
        ])
        self.assertEqual(code, 1)
        payload = json.loads(out_path.read_text(encoding="utf-8"))
        self.assertEqual(len(payload["rules"]), 8)


if __name__ == "__main__":
    unittest.main(verbosity=2)
