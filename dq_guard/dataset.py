"""CSV / TSV 读取。

刻意**不做**隐式类型转换：所有值保持字符串原样。
原因：数据质量检查首先要能区分「值为空」和「值填错了」，
如果读取阶段就把 `abc` 转成 NaN，这两种情况就被合并了，规则再也分不清。
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import List

from .base import Dataset, RuleError

#: 可能遇到的编码，按顺序尝试
_ENCODING_CANDIDATES = ("utf-8-sig", "utf-8", "gb18030")


def _read_text_rows(path: Path, encoding: str, delimiter: str) -> List[List[str]]:
    with path.open("r", encoding=encoding, newline="") as fh:
        reader = csv.reader(fh, delimiter=delimiter)
        return [row for row in reader]


def load_dataset(
    path: Path,
    fmt: str = "csv",
    encoding: str = "utf-8-sig",
    delimiter: str | None = None,
    *,
    allow_encoding_fallback: bool = True,
) -> Dataset:
    """读取数据集，返回保持原始字符串的 :class:`Dataset`。"""
    path = Path(path)
    if not path.exists():
        raise RuleError(f"数据文件不存在: {path}")

    sep = delimiter or ("\t" if fmt == "tsv" else ",")

    encodings = [encoding]
    if allow_encoding_fallback:
        encodings += [e for e in _ENCODING_CANDIDATES if e != encoding]

    last_error: Exception | None = None
    rows: List[List[str]] = []
    used_encoding = encoding
    for enc in encodings:
        try:
            rows = _read_text_rows(path, enc, sep)
            used_encoding = enc
            break
        except UnicodeDecodeError as exc:
            last_error = exc
            continue

    if not rows:
        if last_error is not None:
            raise RuleError(
                f"无法解码 {path}（尝试过 {encodings}）: {last_error}"
            ) from last_error
        raise RuleError(f"{path} 是空文件，至少需要一行表头")

    header, body = rows[0], rows[1:]
    columns = _dedupe_header(header)

    records = []
    for row in body:
        # 行短于表头时补空串；行长于表头时多余部分丢弃（并在报告里由行数体现）
        padded = list(row) + [""] * (len(columns) - len(row))
        records.append(dict(zip(columns, padded[: len(columns)])))

    ds = Dataset(columns=columns, rows=records, source=str(path))
    # 便于报告显示实际使用的编码
    setattr(ds, "encoding", used_encoding)
    return ds


def _dedupe_header(header: List[str]) -> List[str]:
    """表头去重：重复列名追加 _2/_3，空列名补 col_N。"""
    out: List[str] = []
    seen: dict[str, int] = {}
    for idx, name in enumerate(header):
        clean = (name or "").strip() or f"col_{idx + 1}"
        if clean in seen:
            seen[clean] += 1
            clean = f"{clean}_{seen[clean]}"
        else:
            seen[clean] = 1
        out.append(clean)
    return out
