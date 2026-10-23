"""规则 DSL：解析、校验、把配置变成可执行对象。

DSL 形状（JSON 原生；装了 PyYAML 后 .yaml/.yml 也可以）
------------------------------------------------------
```json
{
  "version": 1,
  "dataset": {
    "path": "examples/sample.csv",
    "format": "csv",
    "encoding": "utf-8-sig",
    "delimiter": null
  },
  "report": { "format": "markdown", "path": null, "samples": 5, "title": "数据质量报告" },
  "options": { "fail_on": "error", "as_of": null },
  "rules": [
    { "id": "box_id_not_null", "type": "not_null", "column": "box_id", "severity": "error" },
    { "id": "box_id_unique",   "type": "unique",   "columns": ["box_id"], "severity": "error" }
  ]
}
```

约定
----
- `dataset.path` 若为相对路径，**相对配置文件所在目录**解析——这样在任何 cwd 下
  运行结果都一致。
- `report.path` 同样相对配置文件目录。
- 每条规则的 `severity` 可省略，默认 `error`。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

SUPPORTED_VERSIONS = (1,)
FAIL_ON_CHOICES = ("error", "warn", "info", "none")


class ConfigError(Exception):
    """配置文件本身有问题（格式、字段、路径）。"""


@dataclass
class DatasetSpec:
    path: Path
    format: str = "csv"
    encoding: str = "utf-8-sig"
    delimiter: Optional[str] = None


@dataclass
class ReportSpec:
    format: str = "markdown"
    path: Optional[Path] = None
    samples: int = 5
    title: str = "数据质量报告"


@dataclass
class OptionsSpec:
    fail_on: str = "error"
    as_of: Optional[str] = None


@dataclass
class Config:
    dataset: DatasetSpec
    report: ReportSpec
    options: OptionsSpec
    rules: List[Dict[str, Any]] = field(default_factory=list)
    source: Optional[Path] = None


# ---------------------------------------------------------------- 读取


def _read_mapping(path: Path) -> Dict[str, Any]:
    suffix = path.suffix.lower()
    text = path.read_text(encoding="utf-8-sig")

    if suffix == ".json":
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ConfigError(f"{path}: JSON 解析失败 — {exc}") from exc
    elif suffix in (".yaml", ".yml"):
        try:
            import yaml  # 可选依赖
        except ImportError as exc:
            raise ConfigError(
                f"{path}: 读取 YAML 需要 PyYAML（pip install 'dq-guard[yaml]'），"
                "或改用 .json 配置"
            ) from exc
        try:
            data = yaml.safe_load(text)
        except Exception as exc:  # noqa: BLE001 - yaml 的异常类型不统一
            raise ConfigError(f"{path}: YAML 解析失败 — {exc}") from exc
    else:
        raise ConfigError(
            f"{path}: 不支持的配置后缀 {suffix!r}，请用 .json / .yaml / .yml"
        )

    if not isinstance(data, dict):
        raise ConfigError(f"{path}: 配置顶层必须是一个对象（mapping）")
    return data


def _resolve(base: Path, raw: Optional[str]) -> Optional[Path]:
    """相对路径按 base 解析。"""
    if not raw:
        return None
    p = Path(raw)
    return p if p.is_absolute() else (base / p)


# ---------------------------------------------------------------- 校验


def _as_str(data: Dict[str, Any], key: str, default: Optional[str] = None) -> Optional[str]:
    value = data.get(key, default)
    if value is not None and not isinstance(value, str):
        raise ConfigError(f"字段 {key!r} 应为字符串，实际是 {type(value).__name__}")
    return value


def _as_int(data: Dict[str, Any], key: str, default: int) -> int:
    value = data.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ConfigError(f"字段 {key!r} 应为整数，实际是 {type(value).__name__}")
    return value


def load_config(path: str | Path) -> Config:
    """读取并校验配置文件。"""
    cfg_path = Path(path)
    if not cfg_path.exists():
        raise ConfigError(f"配置文件不存在: {cfg_path}")

    raw = _read_mapping(cfg_path)
    base = cfg_path.parent

    version = raw.get("version", 1)
    if version not in SUPPORTED_VERSIONS:
        raise ConfigError(
            f"不支持的 version={version!r}，当前支持 {SUPPORTED_VERSIONS}"
        )

    # ---- dataset
    ds_raw = raw.get("dataset")
    if not isinstance(ds_raw, dict):
        raise ConfigError("缺少 dataset 段，或它不是对象")
    ds_path = _resolve(base, _as_str(ds_raw, "path"))
    if ds_path is None:
        raise ConfigError("dataset.path 不能为空")
    if not ds_path.exists():
        raise ConfigError(f"数据文件不存在: {ds_path}（按配置文件目录解析）")

    dataset = DatasetSpec(
        path=ds_path,
        format=(_as_str(ds_raw, "format") or ds_path.suffix.lstrip(".") or "csv").lower(),
        encoding=_as_str(ds_raw, "encoding", "utf-8-sig") or "utf-8-sig",
        delimiter=_as_str(ds_raw, "delimiter"),
    )
    if dataset.format not in ("csv", "tsv"):
        raise ConfigError(f"dataset.format 只支持 csv / tsv，实际是 {dataset.format!r}")

    # ---- report
    rp_raw = raw.get("report") or {}
    if not isinstance(rp_raw, dict):
        raise ConfigError("report 段必须是对象")
    report = ReportSpec(
        format=(_as_str(rp_raw, "format", "markdown") or "markdown").lower(),
        path=_resolve(base, _as_str(rp_raw, "path")),
        samples=max(0, _as_int(rp_raw, "samples", 5)),
        title=_as_str(rp_raw, "title", "数据质量报告") or "数据质量报告",
    )
    if report.format not in ("markdown", "md", "html", "json"):
        raise ConfigError(
            f"report.format 只支持 markdown / html / json，实际是 {report.format!r}"
        )

    # ---- options
    op_raw = raw.get("options") or {}
    if not isinstance(op_raw, dict):
        raise ConfigError("options 段必须是对象")
    fail_on = (_as_str(op_raw, "fail_on", "error") or "error").lower()
    if fail_on not in FAIL_ON_CHOICES:
        raise ConfigError(
            f"options.fail_on 只支持 {FAIL_ON_CHOICES}，实际是 {fail_on!r}"
        )
    options = OptionsSpec(fail_on=fail_on, as_of=_as_str(op_raw, "as_of"))

    # ---- rules
    rules_raw = raw.get("rules")
    if not isinstance(rules_raw, list) or not rules_raw:
        raise ConfigError("rules 必须是非空数组")
    rules: List[Dict[str, Any]] = []
    seen_ids = set()
    for i, item in enumerate(rules_raw):
        if not isinstance(item, dict):
            raise ConfigError(f"rules[{i}] 必须是对象")
        if not item.get("type"):
            raise ConfigError(f"rules[{i}] 缺少 type 字段")
        rid = item.get("id") or f"{item['type']}_{i}"
        if rid in seen_ids:
            raise ConfigError(f"规则 id 重复: {rid!r}")
        seen_ids.add(rid)
        rules.append({**item, "id": rid})

    return Config(
        dataset=dataset,
        report=report,
        options=options,
        rules=rules,
        source=cfg_path,
    )
