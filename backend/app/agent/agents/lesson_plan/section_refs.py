"""章节 ID 规范化层。

核心原则（修复方案 §3.1）：
- 章节 ID 只能在请求入口转换一次；执行阶段只允许使用规范 ID（`SEC-*`）。
- 旧别名（如 ``reflection`` → ``SEC-REFLECTION``）只在入口兼容映射，Agent/工具内部
  禁止再次猜测章节 ID。
- 章节索引必须递归扫描所有层级，不只扫描顶层章节。
- 未知 ID 立即返回结构化错误（``invalid_section_id``），由调用方决定拒绝方式。
"""

from __future__ import annotations

from typing import Any

# 历史别名 → 规范章节 ID（兼容旧前端/旧消息，只允许在入口转换）。
SECTION_ID_ALIASES: dict[str, str] = {
    "reflection": "SEC-REFLECTION",
    "assessment": "SEC-ASSESSMENT",
    "SEC-REFLECTION": "SEC-REFLECTION",
    "SEC-ASSESSMENT": "SEC-ASSESSMENT",
}

_INVALID_ALIAS = object()


def _resolve_alias(raw: str) -> str | None:
    """仅当别名表显式包含时才转换；未知 ID 返回 None（交给索引校验）。"""
    return SECTION_ID_ALIASES.get(str(raw).strip())


def build_section_index(content: dict[str, Any]) -> set[str]:
    """递归收集大纲全部章节 ID（任意层级，非仅顶层）。"""
    index: set[str] = set()

    def visit(sections: list[Any]) -> None:
        for item in sections or []:
            sid = str(item.get("id") or "").strip()
            if sid:
                index.add(sid)
            visit(item.get("children") or [])

    visit((content.get("outline") or {}).get("sections") or [])
    return index


def canonicalize_section_ids(
    raw_ids: list[str] | None,
    section_index: set[str] | None = None,
) -> tuple[list[str], list[str]]:
    """把原始章节 ID 列表规范化为规范 ID。

    - 别名映射（reflection → SEC-REFLECTION）；
    - 已存在的规范 ID 直接通过；
    - 提供 ``section_index`` 时校验存在性：未知 ID 进入 ``invalid_ids``；
    - 未提供索引时仅做别名映射（保留未知项，由调用方决定）。
    """
    if not raw_ids:
        return [], []
    canonical: list[str] = []
    invalid: list[str] = []
    for raw in raw_ids:
        if raw is None:
            continue
        resolved = _resolve_alias(str(raw)) or str(raw).strip()
        if not resolved:
            continue
        if section_index is not None and resolved not in section_index:
            invalid.append(str(raw))
            continue
        if resolved not in canonical:
            canonical.append(resolved)
    return canonical, invalid


def canonicalize_single(raw_id: str | None, section_index: set[str] | None = None) -> str | None:
    """单个 ID 规范化（返回 None 表示无效/未知）。"""
    if not raw_id:
        return None
    canonical, invalid = canonicalize_section_ids([raw_id], section_index)
    return canonical[0] if canonical and not invalid else None


# ---------------------------------------------------------------------------
# 内容接地（Content Grounding）：把教师指令中的自然语言引用映射到当前大纲的
# 真实章节 ID。这是意图识别的一部分，替代旧的“业务特化硬编码规则”——目标范围
# 一律从当前文档结构解析，而不是从预设关键词表猜测。
# ---------------------------------------------------------------------------

#: 稳定事实键 → 常见教学术语别名（用于把指令词映射到章节的 coverage_refs）。
FACT_ALIASES: dict[str, tuple[str, ...]] = {
    "objectives": ("目标", "教学目标", "学习目标"),
    "stages": ("环节", "过程", "教学环节", "课堂活动", "活动"),
    "key_points": ("重点", "教学重点"),
    "difficulty_points": ("难点", "教学难点"),
    "methods": ("方法", "策略", "教学策略"),
    "resources": ("资源", "教具"),
    "assessment_plan": ("评价", "教学评价", "评估"),
    "homework": ("作业", "课后练习"),
    "board_design": ("板书", "板书设计"),
    "reflection": ("反思", "教学反思", "课后反思"),
    "content_analysis": ("内容分析", "教材分析", "教学内容"),
    "learner_analysis": ("学情", "学情分析", "学生分析"),
}


def _title_tokens(title: str) -> list[str]:
    """把章节标题拆成可匹配的中文词元（≥2 字符的词）。"""
    if not title:
        return []
    import re

    return [tok for tok in re.findall(r"[\u4e00-\u9fff]{2,}", title) if tok]


def ground_instruction_sections(
    instruction: str,
    content: dict[str, Any] | None,
    requested_ids: list[str] | None = None,
    *,
    top_n: int = 4,
) -> list[str]:
    """把教师指令接地到当前大纲的真实章节 ID。

    - ``requested_ids``（用户显式选中）优先保留；
    - 无大纲内容时返回规范化的 requested_ids（别名映射到 SEC-*）；
    - 评分：章节标题词元直接命中（+4）＞ 事实键别名命中（+2）＞ 父标题命中（+1）；
    - 返回按分数降序的真实章节 ID（均经别名规范化），最多 ``top_n`` 个。
    """
    requested = [str(sid) for sid in (requested_ids or []) if str(sid)]
    outline = (content or {}).get("outline") or {}
    sections = list(outline.get("sections") or [])
    if not sections:
        canonical, _ = canonicalize_section_ids(requested, None)
        return canonical
    compact = "".join((instruction or "").split())

    scores: dict[str, int] = {}

    def visit(items: list[dict[str, Any]], parent_title: str) -> None:
        for node in items or []:
            sid = str(node.get("id") or "")
            title = str(node.get("title") or "")
            refs = list(node.get("coverage_refs") or [])
            score = 0
            if title and title in compact:
                score += 4
            elif title:
                for token in _title_tokens(title):
                    if token and token in compact:
                        score += 3
                        break
            for ref in refs:
                for alias in FACT_ALIASES.get(ref, ()):
                    if alias in compact:
                        score += 2
                        break
            if parent_title and parent_title in compact:
                score += 1
            if score:
                scores[sid] = score
            visit(node.get("children") or [], title)

    visit(sections, "")
    if not scores:
        return list(canonicalize_section_ids(requested, None)[0])
    ordered = sorted(scores, key=lambda sid: (-scores[sid], sid))
    result = [sid for sid in ordered if sid][:top_n]
    if requested:
        # 用户显式选中的章节保留（去重），即使分数低于接地结果。
        result = list(dict.fromkeys(requested + result))
    # 统一映射别名（reflection → SEC-REFLECTION），保证返回均为规范章节 ID。
    canonical, _ = canonicalize_section_ids(result, None)
    return canonical


def coverage_refs_for_sections(content: dict[str, Any] | None, section_ids: list[str]) -> list[str]:
    """返回指定章节的事实覆盖键（用于派生 target_fact_keys）。"""
    refs: set[str] = set()
    for node, _parent, _order, _depth in walk_all_sections((content or {}).get("outline") or {}):
        if str(node.get("id") or "") in set(section_ids):
            refs.update(node.get("coverage_refs") or [])
    return sorted(refs)


def walk_all_sections(outline: dict[str, Any]):
    """递归遍历大纲全部章节节点（供接地/派生使用）。"""
    result: list[tuple[dict[str, Any], str, int, int]] = []

    def visit(items: list[dict[str, Any]], parent_id: str, depth: int) -> None:
        for order, item in enumerate(items or []):
            result.append((item, parent_id, order, depth))
            visit(item.get("children") or [], str(item.get("id") or ""), depth + 1)

    visit(list(outline.get("sections") or []), "", 1)
    return result
