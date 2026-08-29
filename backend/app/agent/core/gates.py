"""Agent 交互门禁总开关。

relaxed（默认）：交互修改按教师意图直接执行——
- 意图识别不再因低置信度/破坏性关键词/目标无法解析而暂停等待确认；
- 工具层作用域守卫、高风险确认令牌不再拒绝调用；
- 发布环节只保留防数据损坏的结构校验，教学质询/范围完整性等降级为 diagnostics；
- QA 返修闭环不再阻断发布。

strict：保留全部历史门禁行为，用于回滚对照。

各门禁点通过 ``gates_active()`` 判断；开关收敛在本模块，便于日后彻底移除。
"""

from __future__ import annotations

from app.core.config import get_settings


def gates_active() -> bool:
    """True = strict 模式，门禁全部生效；False = relaxed，门禁旁路。"""
    mode = getattr(get_settings(), "agent_gates_mode", "relaxed")
    return str(mode).lower() == "strict"
