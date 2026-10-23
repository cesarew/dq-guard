"""规则注册入口。

新增一条规则的完整步骤
----------------------
1. 在本目录新建 ``<规则名>.py``；
2. 定义 ``Rule`` 子类，填 ``type_name`` / ``required`` / ``description``；
3. 用 ``@register`` 装饰，并实现 ``check()``；
4. **在下面加一行 import**——注册依赖 import 的副作用，忘了这一步规则不会出现；
5. 在 ``tests/test_engine.py`` 里加测试。

未实现的规则
------------
如果暂时只写接口不写实现，``check()`` 里抛 ``NotImplementedError`` 即可：
引擎会把它记为「未执行」而不是让整个检查崩掉，并在报告里显式标出。
**静默失败必须可见**——一条规则没跑，报告里必须能看出来。
当前所有规则均已实现，该机制保留给后续新增规则使用。
"""

from __future__ import annotations

from .cross_column import CrossColumnRule  # noqa: F401
from .enum import EnumRule  # noqa: F401
from .funnel import FunnelRule  # noqa: F401
from .lat_lng_swapped import LatLngSwappedRule  # noqa: F401
from .not_null import NotNullRule  # noqa: F401
from .range_rule import RangeRule  # noqa: F401
from .unique import UniqueRule  # noqa: F401
from .unit_consistency import UnitConsistencyRule  # noqa: F401

#: 尚未实现的规则类型名，供 CLI 的 --list-rules 展示。
#: 新增规则但暂不实现时，把 type_name 加进来即可。
PENDING_RULES: tuple = ()
