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
