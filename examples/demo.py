#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dq-guard 现场演示 —— 六幕演完 8 条规则与 3 种退出码。

    python examples/demo.py                 # 在仓库里直接跑
    python examples/demo.py --repo <path>   # 对另一个副本跑（例如已发布的 tag）
    python examples/demo.py --workdir <p>   # 改中间产物目录（默认 out/demo-work）

设计要点
--------
1. **不是"永远红"的演示**：坏数据必须红，修复后必须绿。只有两侧都演，
   才能证明规则是在"抓缺陷"而不是"见谁都抓"。
2. **覆盖三种退出码**：1（触发阈值）/ 0（通过）/ 2（配置错误）。
   CI 集成靠的正是这三个码。
3. **自校验**：每个 ACT 都断言退出码与关键输出片段，不符就整体 exit 1。
   演示脚本自己不验证，就没有说服力。

产物（默认都在被 gitignore 的 out/ 下）：
    out/demo-work/     生成的数据与规则配置
    out/demo-report/   HTML / JSON / Markdown 报告
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_DEFAULT = Path(__file__).resolve().parent.parent

FAILURES: list[str] = []
STEPS = 0


# ---------------------------------------------------------------- 输出工具
def title(text: str) -> None:
    print("\n" + "=" * 78)
    print(text)
    print("=" * 78)


def check(desc: str, ok: bool, detail: str = "") -> None:
    global STEPS
    STEPS += 1
    print(f"  [{'PASS' if ok else 'FAIL'}] {desc}" + ("" if ok else f"  <- {detail}"))
    if not ok:
        FAILURES.append(desc)


def run_cli(repo: Path, args: list[str]) -> tuple[int, str, str]:
    """以 `python -m dq_guard` 方式调用，强制 UTF-8，避免 Windows 控制台 GBK 崩 emoji。"""
    env = {
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
        "PATH": os.environ.get("PATH", ""),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
    }
    proc = subprocess.run(
        [sys.executable, "-m", "dq_guard", *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    return proc.returncode, proc.stdout or "", proc.stderr or ""


# ---------------------------------------------------------------- 造数据
# 12 行仓位快照，每行植入一类缺陷；注释标出哪条规则会抓到它
BOXES_BAD = """station_id,box_id,latitude,longitude,status,soc,battery_no,temperature,temp_limit
S001,B001,39.9219,116.4434,0,88,BT0001,32.5,45.0
S001,B002,39.9219,116.4434,1,,BT0002,33.1,45.0
S002,,39.9231,116.4402,0,95,,31.0,45.0
S002,B002,39.9231,116.4402,0,95,BT0003,30.8,45.0
S003,B003,116.4510,39.9187,0,61,BT0004,34.2,45.0
S003,B004,39.9187,116.4510,0,150,BT0005,36.7,45.0
S004,B005,39.9061,116.3975,9,73,BT0006,35.0,45.0
S004,B006,39.9061,116.3975,0,-3,BT0007,29.9,45.0
S005,B007,39.9123,116.4211,0,42,BT0008,48.6,45.0
S005,B008,39.9123,116.4211,2,77,,33.4,45.0
S006,B009,39.9302,116.4688,0,64,BT0010,31.7,45.0
S006,B010,39.9302,116.4688,1,58,BT0011,30.2,45.0
"""

# 修复版：空值补齐、重复编号改写、经纬度换回、越界值修正、非法枚举归位、温度回落到上限内
BOXES_FIXED = """station_id,box_id,latitude,longitude,status,soc,battery_no,temperature,temp_limit
S001,B001,39.9219,116.4434,0,88,BT0001,32.5,45.0
S001,B002,39.9219,116.4434,1,73,BT0002,33.1,45.0
S002,B012,39.9231,116.4402,0,95,BT0012,31.0,45.0
S002,B0021,39.9231,116.4402,0,95,BT0003,30.8,45.0
S003,B003,39.9187,116.4510,0,61,BT0004,34.2,45.0
S003,B004,39.9187,116.4510,0,100,BT0005,36.7,45.0
S004,B005,39.9061,116.3975,1,73,BT0006,35.0,45.0
S004,B006,39.9061,116.3975,0,0,BT0007,29.9,45.0
S005,B007,39.9123,116.4211,0,42,BT0008,44.9,45.0
S005,B008,39.9123,116.4211,2,77,BT0009,33.4,45.0
S006,B009,39.9302,116.4688,0,64,BT0010,31.7,45.0
S006,B010,39.9302,116.4688,1,58,BT0011,30.2,45.0
"""

FUNNEL_BAD = """stage_order,stage_name,input_rows,output_rows
1,raw,150,150
2,dedup,150,147
3,quality,147,150
4,export,150,150
"""

FUNNEL_FIXED = """stage_order,stage_name,input_rows,output_rows
1,raw,150,150
2,dedup,150,147
3,quality,147,140
4,export,140,140
"""

ENERGY_BAD = """device_id,battery_kwh,quantity_raw
D001,886.7,886667.9
D002,120.5,120500.0
D003,0,150000.0
D004,540.2,540200.0
D005,95.4,954000.0
"""

ENERGY_FIXED = """device_id,battery_kwh,quantity_raw
D001,886.7,886667.9
D002,120.5,120500.0
D003,0,150000.0
D004,540.2,540200.0
D005,954.0,954000.0
"""


def rules_for_boxes(work: Path, data_file: str) -> dict:
    return {
        "version": 1,
        "dataset": {"path": data_ref(work, data_file), "format": "csv", "encoding": "utf-8-sig"},
        "report": {"format": "markdown", "path": None, "samples": 3,
                   "title": "换电柜仓位数据质量报告"},
        "options": {"fail_on": "error"},
        "rules": [
            {"id": "box_id_not_null", "type": "not_null", "column": "box_id",
             "severity": "error", "description": "仓位编号必填，缺失无法定位仓位",
             "evidence": ["station_id", "box_id"]},
            {"id": "soc_not_null", "type": "not_null", "column": "soc",
             "severity": "error", "description": "电量率必填，缺失会让下游指标静默降级",
             "evidence": ["station_id", "box_id", "soc"]},
            {"id": "box_id_unique", "type": "unique", "columns": ["box_id"],
             "severity": "error", "description": "仓位编号单期内唯一，重复说明关联放大了数据",
             "evidence": ["station_id", "box_id"]},
            {"id": "latitude_in_range", "type": "range", "column": "latitude",
             "min": 39.0, "max": 41.1, "severity": "error",
             "description": "北京区域纬度范围", "evidence": ["station_id", "box_id", "latitude"]},
            {"id": "longitude_in_range", "type": "range", "column": "longitude",
             "min": 115.4, "max": 117.6, "severity": "error",
             "description": "北京区域经度范围", "evidence": ["station_id", "box_id", "longitude"]},
            {"id": "soc_in_range", "type": "range", "column": "soc",
             "min": 0, "max": 100, "severity": "error",
             "description": "电量率是百分数，须落在 [0,100]", "evidence": ["station_id", "soc"]},
            {"id": "status_in_enum", "type": "enum", "column": "status",
             "values": ["0", "1", "2"], "severity": "warn",
             "description": "0=正常 1=故障 2=禁用，其他值说明状态字典没跟上",
             "evidence": ["station_id", "box_id", "status"]},
            {"id": "coords_not_swapped", "type": "lat_lng_swapped",
             "lat_column": "latitude", "lng_column": "longitude", "severity": "error",
             "description": "经纬度两列是否写反（中国范围内判定，结论为疑似）",
             "evidence": ["station_id", "box_id", "latitude", "longitude"]},
            {"id": "temperature_under_limit", "type": "cross_column",
             "left": "temperature", "op": "<=", "right_column": "temp_limit",
             "severity": "error", "description": "仓温不得超过该仓上限（过温需人工介入）",
             "evidence": ["station_id", "box_id", "temperature", "temp_limit"]},
        ],
    }


def rules_for_funnel(work: Path, data_file: str) -> dict:
    return {
        "version": 1,
        "dataset": {"path": data_ref(work, data_file), "format": "csv", "encoding": "utf-8-sig"},
        "report": {"format": "markdown", "path": None, "samples": 5,
                   "title": "语料清洗漏斗不变量检查"},
        "options": {"fail_on": "error"},
        "rules": [{"id": "funnel_monotonic", "type": "funnel",
                   "input_column": "input_rows", "output_column": "output_rows",
                   "name_column": "stage_name", "strict": True, "severity": "error",
                   "description": "各阶段产出不得多于投入，且下一阶段投入应等于上一阶段产出"}],
    }


def rules_for_energy(work: Path, data_file: str) -> dict:
    return {
        "version": 1,
        "dataset": {"path": data_ref(work, data_file), "format": "csv", "encoding": "utf-8-sig"},
        "report": {"format": "markdown", "path": None, "samples": 5,
                   "title": "用电量单位一致性检查"},
        "options": {"fail_on": "error"},
        "rules": [{"id": "energy_unit_consistent", "type": "unit_consistency",
                   "primary": "battery_kwh", "secondary": "quantity_raw",
                   "factor": 0.001, "tolerance": 0.05, "severity": "error",
                   "description": "主字段（度）应等于备用字段（千分之一度）×0.001；主字段为 0 时跳过",
                   "evidence": ["device_id", "battery_kwh", "quantity_raw"]}],
    }


def data_ref(work: Path, name: str) -> str:
    """配置里的数据路径按「配置文件所在目录」解析（dq_guard/spec.py: base = cfg.parent）。

    所以这里算一条从 <work>/rules/ 指向 <work>/ 的相对路径，而不是写死 `../work/`——
    写死的话会变成 work/work/x，这是本演示第一次跑时踩到的坑。
    """
    return Path(os.path.relpath(work / name, work / "rules")).as_posix()


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def prepare(work: Path, out: Path, rebuild: bool = True) -> None:
    if rebuild:
        for p in (work, out):
            if p.exists():
                shutil.rmtree(p)
    work.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)

    for name, text in (
        ("boxes_bad.csv", BOXES_BAD), ("boxes_fixed.csv", BOXES_FIXED),
        ("funnel_bad.csv", FUNNEL_BAD), ("funnel_fixed.csv", FUNNEL_FIXED),
        ("energy_bad.csv", ENERGY_BAD), ("energy_fixed.csv", ENERGY_FIXED),
    ):
        (work / name).write_text(text, encoding="utf-8-sig")

    write_json(work / "rules" / "boxes_bad.json", rules_for_boxes(work, "boxes_bad.csv"))
    write_json(work / "rules" / "boxes_fixed.json", rules_for_boxes(work, "boxes_fixed.csv"))
    write_json(work / "rules" / "funnel_bad.json", rules_for_funnel(work, "funnel_bad.csv"))
    write_json(work / "rules" / "funnel_fixed.json", rules_for_funnel(work, "funnel_fixed.csv"))
    write_json(work / "rules" / "energy_bad.json", rules_for_energy(work, "energy_bad.csv"))
    write_json(work / "rules" / "energy_fixed.json", rules_for_energy(work, "energy_fixed.csv"))
    write_json(work / "rules" / "broken.json", {"version": 1, "rules": [{"id": "x"}]})


def main() -> int:
    ap = argparse.ArgumentParser(description="dq-guard 六幕演示（自校验）")
    ap.add_argument("--repo", default=str(REPO_DEFAULT), help="dq-guard 仓库根目录")
    ap.add_argument("--workdir", default=None, help="中间产物目录，默认 <repo>/out/demo-work")
    ap.add_argument("--keep", action="store_true", help="保留上一轮的中间产物，不重建")
    args = ap.parse_args()

    repo = Path(args.repo).resolve()
    work = Path(args.workdir).resolve() if args.workdir else repo / "out" / "demo-work"
    out = work.parent / "demo-report"

    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass

    if not (repo / "dq_guard").is_dir():
        print(f"找不到 dq-guard 仓库：{repo}")
        return 2

    prepare(work, out, rebuild=not args.keep)

    # ---------------- ACT 1
    title("ACT 1  规则清单：装了哪些检查能力")
    code, out_s, err = run_cli(repo, ["--list-rules"])
    print(out_s.rstrip())
    check("--list-rules 退出码为 0", code == 0, f"实际 {code} {err[:80]}")
    check("规则数为 8 条", "8 条规则" in out_s, out_s[-60:])

    # ---------------- ACT 2
    title("ACT 2  坏数据体检：仓位表（12 行植入 9 类缺陷）")
    print("逐行植入了：空编号 / 空电量 / 重复编号 / 经纬度写反 / 电量越界 / 非法枚举 / 仓温超上限")
    code, out_s, err = run_cli(repo, [str(work / "rules" / "boxes_bad.json")])
    print(out_s.rstrip()[:2200])
    check("坏数据退出码为 1（CI 会拦下）", code == 1, f"实际 {code}")
    for needle, desc in [
        ("box_id_not_null", "抓到空仓位编号"),
        ("soc_not_null", "抓到空电量率"),
        ("box_id_unique", "抓到重复仓位编号"),
        ("coords_not_swapped", "抓到经纬度写反"),
        ("soc_in_range", "抓到电量率越界"),
        ("status_in_enum", "抓到非法状态枚举"),
        ("temperature_under_limit", "抓到仓温超上限"),
    ]:
        check(desc, needle in out_s, "报告里没有该规则")

    # ---------------- ACT 3
    title("ACT 3  漏斗与单位：跨阶段、跨字段的两类缺陷")
    code_f, out_f, _ = run_cli(repo, [str(work / "rules" / "funnel_bad.json")])
    print("--- 漏斗：某阶段产出多于投入 ---")
    print(out_f.rstrip()[:900])
    check("漏斗坏数据退出码为 1", code_f == 1, f"实际 {code_f}")

    code_e, out_e, _ = run_cli(repo, [str(work / "rules" / "energy_bad.json")])
    print("\n--- 单位：主字段与备用字段差 10 倍 ---")
    print(out_e.rstrip()[:900])
    check("单位坏数据退出码为 1", code_e == 1, f"实际 {code_e}")

    # ---------------- ACT 4
    title("ACT 4  修复后复跑：证明规则不是见谁都抓")
    print("同一批规则，换成修复后的数据 —— 三套都必须转绿。")
    for name in ("boxes_fixed", "funnel_fixed", "energy_fixed"):
        code_r, out_r, err_r = run_cli(repo, [str(work / "rules" / f"{name}.json"), "--quiet"])
        print(f"  {name:<14} -> exit={code_r}  {out_r.strip()}")
        check(f"{name} 修复后退出码为 0", code_r == 0, f"实际 {code_r} {err_r[:100]}")

    # ---------------- ACT 5
    title("ACT 5  产出可交付物：HTML / JSON / 只报错不阻断")
    code_h, _, _ = run_cli(repo, [str(work / "rules" / "boxes_bad.json"),
                                  "--format", "html",
                                  "--report", str(out / "boxes_bad.html")])
    html_path = out / "boxes_bad.html"
    check("HTML 报告已生成", html_path.exists() and html_path.stat().st_size > 2000,
          f"size={html_path.stat().st_size if html_path.exists() else 0}")
    check("HTML 模式下退出码仍为 1", code_h == 1, f"实际 {code_h}")

    _, _, _ = run_cli(repo, [str(work / "rules" / "boxes_bad.json"),
                             "--format", "json",
                             "--report", str(out / "boxes_bad.json")])
    json_path = out / "boxes_bad.json"
    check("JSON 报告已生成", json_path.exists())
    if json_path.exists():
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        # JSON 结构：顶层 rules[]，每条有 rule_id / passed / failed / failed_rows
        rules = payload.get("rules", [])
        n_failed = sum(1 for r in rules if not r.get("passed", True))
        check("JSON 顶层 passed 为 false", payload.get("passed") is False, str(payload.get("passed")))
        check("JSON 行数等于 12", payload.get("row_count") == 12, str(payload.get("row_count")))
        check("JSON 里 9 条规则全部失败（植入的缺陷全被抓到）",
              len(rules) == 9 and n_failed == 9, f"rules={len(rules)} failed={n_failed}")

    code_q, out_q, _ = run_cli(repo, [str(work / "rules" / "boxes_bad.json"),
                                      "--quiet", "--fail-on", "none",
                                      "--report", str(out / "report_only.md")])
    check("--fail-on none 时退出码为 0（只出报告，不阻断流水线）", code_q == 0, f"实际 {code_q}")
    print(f"  摘要行：{out_q.strip()}")

    # ---------------- ACT 6
    title("ACT 6  配置坏了要报错，不能静默通过")
    code_b, _, err_b = run_cli(repo, [str(work / "rules" / "broken.json")])
    print(f"  stderr: {err_b.strip()[:160]}")
    check("坏配置退出码为 2", code_b == 2, f"实际 {code_b}")

    # ---------------- 汇总
    title("演示结果")
    print(f"  断言 {STEPS} 项，失败 {len(FAILURES)} 项")
    for f in FAILURES:
        print(f"    - {f}")
    print(f"\n  中间产物: {work}")
    print(f"  报告目录: {out}")
    for p in sorted(out.glob("*")):
        print(f"    {p.name:<20} {p.stat().st_size/1024:>7.1f} KB")
    return 0 if not FAILURES else 1


if __name__ == "__main__":
    sys.exit(main())
