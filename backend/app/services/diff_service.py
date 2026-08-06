"""Diff 算法计算服务。

计算两个版本之间的文本 Unified Diff 与 JSON Patch 差异，
供 Agent 增量编辑与前端 Git-style Diff 视图渲染使用。
"""
import difflib
from typing import Any, Dict, List


def compute_text_diff(old_text: str, new_text: str, context_lines: int = 3) -> List[Dict[str, Any]]:
    """计算文本规范的 Unified Diff Hunks 数据结构。

    返回:
        [
            {
                "old_start": 1,
                "old_lines": 5,
                "new_start": 1,
                "new_lines": 6,
                "lines": [
                    {"type": "context", "content": "  header line"},
                    {"type": "delete", "content": "- old sentence"},
                    {"type": "add", "content": "+ new sentence"},
                ]
            }
        ]
    """
    old_lines = old_text.splitlines()
    new_lines = new_text.splitlines()

    matcher = difflib.SequenceMatcher(None, old_lines, new_lines)
    opcodes = matcher.get_opcodes()

    hunks: List[Dict[str, Any]] = []

    # 简单生成单一 hunk 或按 context 拆分
    current_hunk_lines: List[Dict[str, Any]] = []
    old_start, new_start = 1, 1

    for tag, i1, i2, j1, j2 in opcodes:
        if tag == "equal":
            for line in old_lines[i1:i2]:
                current_hunk_lines.append({"type": "context", "content": f"  {line}"})
        elif tag == "delete":
            for line in old_lines[i1:i2]:
                current_hunk_lines.append({"type": "delete", "content": f"- {line}"})
        elif tag == "insert":
            for line in new_lines[j1:j2]:
                current_hunk_lines.append({"type": "add", "content": f"+ {line}"})
        elif tag == "replace":
            for line in old_lines[i1:i2]:
                current_hunk_lines.append({"type": "delete", "content": f"- {line}"})
            for line in new_lines[j1:j2]:
                current_hunk_lines.append({"type": "add", "content": f"+ {line}"})

    if current_hunk_lines:
        hunks.append({
            "old_start": 1,
            "old_lines": len(old_lines),
            "new_start": 1,
            "new_lines": len(new_lines),
            "lines": current_hunk_lines,
        })

    return hunks


def compute_json_diff(old_data: Any, new_data: Any) -> List[Dict[str, Any]]:
    """简单计算 JSON 数据结构的路径 Patch 变更。

    返回:
        [
            {"op": "add" | "remove" | "replace", "path": "slides[0].title", "value": "New Title"}
        ]
    """
    patches: List[Dict[str, Any]] = []

    def _diff_recursive(p1: Any, p2: Any, path: str):
        if type(p1) != type(p2):
            patches.append({"op": "replace", "path": path, "value": p2})
            return

        if isinstance(p1, dict):
            for k in set(p1.keys()).union(p2.keys()):
                sub_path = f"{path}.{k}" if path else k
                if k not in p1:
                    patches.append({"op": "add", "path": sub_path, "value": p2[k]})
                elif k not in p2:
                    patches.append({"op": "remove", "path": sub_path})
                else:
                    _diff_recursive(p1[k], p2[k], sub_path)
        elif isinstance(p1, list):
            if len(p1) != len(p2):
                patches.append({"op": "replace", "path": path, "value": p2})
            else:
                for idx, (item1, item2) in enumerate(zip(p1, p2)):
                    _diff_recursive(item1, item2, f"{path}[{idx}]")
        else:
            if p1 != p2:
                patches.append({"op": "replace", "path": path, "value": p2})

    _diff_recursive(old_data, new_data, "")
    return patches
