"""通用 Agent 运行时错误。"""

from typing import Any


class AgentError(RuntimeError):
    """稳定的运行时错误，由 Agent/工具抛出并沿任务服务透传给用户。

    ``code`` 是稳定的机器可读错误码（如 lesson_plan 门禁失败、校验失败），
    ``retryable`` 决定任务是否允许重试。
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = True,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.user_message = message
        self.retryable = retryable
        self.details = details or {}


class ToolConfirmationRequired(ValueError):
    """工具命中需要教师确认的高风险操作。

    这类异常不是普通工具故障：Agent 应暂停当前运行并展示确认请求，
    而不是继续重复调用同一个工具直到耗尽轮次。
    """

    error_code = "confirmation_required"

    def __init__(self, message: str, *, operation: str = ""):
        super().__init__(message)
        self.operation = operation
