# dq-guard

**零依赖的声明式数据质量检查工具**，对中文业务数据有一等公民支持。

> **尚未发布到 PyPI**（名称 `dq-guard` 已确认可用，见路线图）。因此现在**没有** `pip install`
> 可用，也没有 `dq-guard` 这个全局命令——请从源码运行，见 [快速开始](#快速开始)。

```bash
git clone https://github.com/cesarew/dq-guard.git && cd dq-guard
python -m dq_guard examples/rules.json     # 打印 Markdown 报告，检出问题退出码 1
```

---

## 为什么又造一个数据质量工具

现有工具都很好，但各有各的门槛：

| 工具 | 问题 |
|---|---|
| Great Expectations | 功能最全，但依赖重、配置学习曲线陡，小管道用不起来 |
| dbt tests | 绑定 dbt，只能跑在 dbt 项目里 |
| Soda / 商业方案 | 要钱或要平台 |

而日常最高频的需求其实很小：**一个 CSV、几条规则、一个能在 CI 里跑的非零退出码**。

更关键的是第二点：**大多数数据质量工具假设欧美数据形态**。
中文业务表里的常见问题不在它们的检查项里：

- **经纬度两列写反**（导出的 Excel 灌库时字段顺序错位）
- **行政区字段大面积空值**（省/市/区没填，或填成 `0`）
- **同一指标多字段、单位不一致**（主字段用「度」，备用字段用「千分之一度」）
- **漏斗崩坏**（过滤后行数反而变多——一对多 JOIN 把数据放大了）

`dq-guard` 把这些变成开箱可用的规则，而不是让每个人再造一遍轮子。

---

## 快速开始

```bash
git clone https://github.com/cesarew/dq-guard.git && cd dq-guard
python -m dq_guard examples/rules.json          # 打印 Markdown 报告
python -m dq_guard examples/rules.json --report out/report.html --format html
python -m dq_guard --list-rules                 # 看有哪些规则、哪些还没实现
```

示例输出（截断）：

```
| 规则 | 类型 | 级别 | 状态 | 检查 | 失败 | 失败率 |
|---|---|---|---|---|---|---|
| `box_id_not_null`   | not_null | 🔴 error | ❌ 失败 | 8 | 1 | 12.50% |
| `box_id_unique`     | unique   | 🔴 error | ❌ 失败 | 8 | 2 | 25.00% |
| `latitude_in_range` | range    | 🔴 error | ❌ 失败 | 8 | 1 | 12.50% |
| `status_in_enum`    | enum     | 🟡 warn  | ❌ 失败 | 8 | 1 | 12.50% |
```

退出码：`0` 通过 / `1` 触发阈值 / `2` 配置或数据错误。

---

## 规则 DSL

写法是一份 `dataset + rules` 的声明，**JSON 原生**，装了 PyYAML 就能写 YAML。

```json
{
  "version": 1,
  "dataset": { "path": "sample.csv", "format": "csv", "encoding": "utf-8-sig" },
  "report":  { "format": "markdown", "path": null, "samples": 5, "title": "数据质量报告" },
  "options": { "fail_on": "error" },
  "rules": [
    {
      "id": "box_id_not_null",
      "type": "not_null",
      "column": "box_id",
      "severity": "error",
      "description": "仓位编号必填",
      "evidence": ["station_id", "box_id"]
    },
    {
      "id": "box_id_unique",
      "type": "unique",
      "columns": ["box_id"],
      "severity": "error"
    },
    {
      "id": "soc_in_range",
      "type": "range",
      "column": "soc",
      "min": 0,
      "max": 100,
      "severity": "error"
    }
  ]
}
```

字段说明：

| 字段 | 必填 | 说明 |
|---|---|---|
| `dataset.path` | ✅ | CSV/TSV 路径；相对路径按**配置文件所在目录**解析 |
| `dataset.encoding` | | 默认 `utf-8-sig`，失败时自动回退 `utf-8` / `gb18030` |
| `report.format` | | `markdown`（默认）/ `html` / `json` |
| `report.samples` | | 每条规则最多保留多少条证据样本，默认 5 |
| `options.fail_on` | | `error`（默认）/ `warn` / `info` / `none` |
| `rules[].id` | | 唯一标识，出现在报告里；重复会报配置错误 |
| `rules[].type` | ✅ | 规则类型，见下表 |
| `rules[].severity` | | `error`（默认）/ `warn` / `info` |
| `rules[].description` | | 人话说明，直接进报告 |
| `rules[].evidence` | | 失败时想看到哪些列；默认只看该规则涉及的列 |

---

## 规则清单

| 类型 | 状态 | 参数 | 说明 |
|---|---|---|---|
| `not_null` | ✅ | `column` | 列不得缺失（空串 / 纯空白 / None） |
| `range` | ✅ | `column`, `min`, `max`, `allow_blank` | 数值落在区间内（含端点） |
| `unique` | ✅ | `columns`（或 `column`） | 取值唯一；重复键的**所有**行都被标出 |
| `enum` | ✅ | `column`, `values`, `allow_blank` | 取值属于白名单 |
| `cross_column` | ✅ | `left`, `op`, `right_column` \| `value` | 两列比较约束（数值优先，否则 `==`/`!=` 退化为字符串比较） |
| `funnel` | ✅ | `input_column`, `output_column`, `strict` | 漏斗不变量：产出不得多于投入，且阶段首尾相接 |
| `lat_lng_swapped` | ✅ | `lat_column`, `lng_column`, `bounds`, `fix` | 经纬度两列是否写反（中国范围内判定，结论为疑似） |
| `unit_consistency` | ✅ | `primary`, `secondary`, `factor`, `tolerance` | 同一指标多字段在指定换算系数下是否一致 |

> 规则机制还支持「先写接口、后写实现」：`check()` 抛 `NotImplementedError` 时，
> 引擎会把它记为**「未执行」**而不是让整个检查崩掉，并在报告里显式标出。
> 一条规则没跑，报告里必须能看出来——静默失败不可接受。

---

## 设计取舍

**1. 值不做类型转换。**
读进来全是字符串。「值为空」和「填了非数字」是两种不同的问题，
如果读取阶段就把 `abc` 转成 NaN，规则就再也分不清了。

**2. 行号是文件行号。**
表头算第 1 行，第一条数据是第 2 行——报告里的行号能直接在 Excel 里跳过去。

**3. 一条规则失败不影响其它规则。**
一次跑完所有规则再汇总：修一次、看全部，而不是修一条跑一遍。

**4. 静默跳过必须可见。**
`range` 跳过空值时、`funnel` 全部跳过时，都会在报告的「口径说明」里写出来。
指标降级不可见 = 埋雷。

---

## 开发

```bash
python -m unittest discover -s tests -v     # 71 个测试，零依赖
```

新增一条规则：在 `dq_guard/rules/` 下建文件 → 定义 `Rule` 子类 → `@register` →
**在 `rules/__init__.py` 里加一行 import**（注册靠 import 副作用）。

---

## 路线图

- [ ] **发布到 PyPI**（`pip install dq-guard` + `dq-guard` 全局命令）
- [ ] 增量检查：只检查新增的日期分区
- [ ] 基线对比：与上一期指标对比，捕捉异常漂移
- [ ] `--fix` 建议模式（只给建议，不改数据）
- [ ] Parquet / 数据库数据源

## License

MIT
