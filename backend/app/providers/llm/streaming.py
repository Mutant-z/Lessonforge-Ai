"""流式 Decision 思考文本提取。

LLM 以 JSON 形式流式返回 AgentDecision，其中 `thinking` 字段是一段 Markdown 思考过程。
ThinkingStreamParser 在增量接收 JSON 文本的过程中，实时提取 `thinking` 字符串值，
供 pipeline 把每个新字符/词块推送到 SSE（前端打字机效果）。

提取是「尽力而为」的：模型不输出 thinking 或结构异常时返回空串，不影响决策解析。
"""


def extract_thinking(text: str) -> str:
    """从（可能不完整的）JSON 文本中提取顶层 `thinking` 字符串值。

    只匹配**顶层对象**（花括号深度 1）中的 `"thinking"` 键，避免误命中嵌套对象里
    的同名键；字符串值允许不完整（JSON 未闭合时返回已接收的部分）。
    """
    n = len(text)
    i = 0
    depth = 0
    while i < n:
        c = text[i]
        if c == '"':
            # 读取一个字符串（键或值）
            j = i + 1
            key_chars: list[str] = []
            while j < n:
                ch = text[j]
                if ch == "\\":
                    key_chars.append(ch)
                    if j + 1 < n:
                        key_chars.append(text[j + 1])
                    j += 2
                    continue
                if ch == '"':
                    break
                key_chars.append(ch)
                j += 1
            else:
                return ""  # 未闭合字符串，JSON 尚不完整
            sval = "".join(key_chars)
            i = j + 1
            if depth == 1 and sval == "thinking":
                # 期望冒号 + 字符串值
                k = i
                while k < n and text[k] in " \t\n\r":
                    k += 1
                if k < n and text[k] == ":":
                    k += 1
                    while k < n and text[k] in " \t\n\r":
                        k += 1
                    if k < n and text[k] == '"':
                        out: list[str] = []
                        kk = k + 1
                        while kk < n:
                            ch2 = text[kk]
                            if ch2 == "\\":
                                if kk + 1 < n:
                                    out.append(text[kk + 1])
                                kk += 2
                                continue
                            if ch2 == '"':
                                break
                            out.append(ch2)
                            kk += 1
                        return "".join(out)
            # 不是 thinking 键；继续扫描（i 已越过该字符串，避免把字符串内 {} 计入深度）
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth = max(0, depth - 1)
        i += 1
    return ""


class ThinkingStreamParser:
    """增量接收 JSON 流文本，返回每批新增的 thinking 字符。"""

    def __init__(self) -> None:
        self._buf = ""
        self._emitted = 0

    def feed(self, chunk: str) -> str:
        """喂入新文本块，返回本次新增的 thinking 文本。"""
        self._buf += chunk
        full = extract_thinking(self._buf)
        new = full[self._emitted:]
        self._emitted = len(full)
        return new

    def finish(self) -> str:
        """返回最终提取的 thinking 文本（供持久化/校验用）。"""
        return extract_thinking(self._buf)
