"""工具实现子包：按领域拆分，每个模块在导入时向 registry 注册工具。

领域划分（对齐需求 §8 统一工具系统）：
- artifact_tools：Artifact 工具
- template_tools：PPT 模板工具
- editing_tools：PPT 编辑工具
- render_tools：PPT 渲染工具
- asset_tools：图片/图表工具
- qa_tools：QA 工具
- workspace_tools：文件工具
"""
from app.agent.tools import (  # noqa: F401
    artifact_tools,
    template_tools,
    editing_tools,
    render_tools,
    asset_tools,
    qa_tools,
    workspace_tools,
)
