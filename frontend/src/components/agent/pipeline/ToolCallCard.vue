<script setup lang="ts">
import { computed, ref } from 'vue';
import { Clock, CircleCheck, CircleClose, Expand, Fold } from '@element-plus/icons-vue';

const props = defineProps<{
  toolName: string;
  agentKey: string;
  input: Record<string, any>;
  output: Record<string, any>;
  ok: boolean;
  error?: string | null;
  durationMs?: number;
}>();

const expanded = ref(false);
const inputSummary = computed(() => summarize(props.input, 120));
const outputSummary = computed(() => summarize(props.output, 160));

function summarize(value: any, limit: number): string {
  if (value == null) return '';
  let text = '';
  try {
    text = JSON.stringify(value);
  } catch {
    text = String(value);
  }
  return text.length > limit ? `${text.slice(0, limit)}…` : text;
}

const toolLabel: Record<string, string> = {
  get_blueprint: '读取课程蓝图',
  get_upstream_artifacts: '读取上游产物',
  get_ppt_source: '读取当前 PPT',
  get_knowledge_base: '读取设计知识库',
  get_template_catalog: '读取模板目录',
  get_template_design: '解析模板设计系统',
  create_slide: '创建幻灯片',
  set_slide_title: '设置标题',
  add_textbox: '添加文本框',
  add_shape: '添加图形',
  add_image: '添加图片',
  add_chart: '添加图表',
  move_element: '移动元素',
  resize_element: '缩放元素',
  delete_element: '删除元素',
  set_element_style: '设置元素样式',
  set_background: '设置背景',
  add_notes: '设置演讲备注',
  write_slide_batch: '批量写入页面内容',
  layout_slide_batch: '批量设置布局几何',
  render_preview: '渲染 PPT 预览',
  render_deck_preview: '渲染模板版式',
  generate_image: '生成图片',
  generate_chart_png: '生成图表',
  render_diagram: '生成示意图',
  run_qa: '运行视觉检查',
  get_qa_report: '读取 QA 报告',
  list_workspace_files: '列出工作区文件',
  read_workspace_file: '读取工作区文件',
  write_workspace_file: '写入工作区文件',
};
</script>

<template>
  <div class="tool-card" :class="{ failed: !ok }">
    <div class="tool-head" @click="expanded = !expanded">
      <span class="tool-status">
        <el-icon v-if="ok" color="#22c55e"><CircleCheck /></el-icon>
        <el-icon v-else color="#ef4444"><CircleClose /></el-icon>
      </span>
      <span class="tool-name">调用工具 · {{ toolLabel[toolName] || toolName }}</span>
      <span class="tool-meta">
        <span v-if="durationMs" class="meta-item"><el-icon><Clock /></el-icon>{{ Math.max(1, durationMs) }}ms</span>
        <el-icon class="expand-icon"><component :is="expanded ? Fold : Expand" /></el-icon>
      </span>
    </div>
    <div class="tool-summary">
      <span class="kv">入参：{{ inputSummary || '—' }}</span>
      <span class="kv" :class="{ err: !ok }">{{ ok ? `结果：${outputSummary || '成功'}` : `失败：${error || '未知错误'}` }}</span>
    </div>
    <div v-if="expanded" class="tool-detail">
      <div class="detail-block">
        <div class="detail-title">完整输入</div>
        <pre>{{ JSON.stringify(input, null, 2) }}</pre>
      </div>
      <div class="detail-block">
        <div class="detail-title">完整输出</div>
        <pre>{{ JSON.stringify(output, null, 2) }}</pre>
      </div>
    </div>
  </div>
</template>

<style scoped>
.tool-card {
  border: 1px solid var(--border, #e5e7eb);
  border-radius: 10px;
  background: var(--surface-primary, #fff);
  margin: 8px 0 8px 18px;
  overflow: hidden;
}
.tool-card.failed { border-color: rgba(239, 68, 68, 0.4); }
.tool-head {
  display: flex; align-items: center; gap: 8px;
  padding: 8px 12px; cursor: pointer;
}
.tool-status { display: inline-flex; }
.tool-name { font-size: 13px; color: #374151; font-weight: 500; }
.tool-meta { margin-left: auto; display: flex; align-items: center; gap: 8px; color: #9ca3af; }
.meta-item { display: inline-flex; align-items: center; gap: 3px; font-size: 12px; }
.expand-icon { font-size: 13px; }
.tool-summary {
  display: flex; flex-direction: column; gap: 2px;
  padding: 0 12px 8px 30px; font-size: 12px; color: #6b7280;
}
.kv.err { color: #ef4444; }
.tool-detail { padding: 8px 12px 12px 30px; }
.detail-block { margin-top: 8px; }
.detail-title { font-size: 12px; color: #9ca3af; margin-bottom: 4px; }
pre {
  background: #f9fafb; border: 1px solid #f0f0f0; border-radius: 6px;
  padding: 8px; font-size: 11px; line-height: 1.5; max-height: 220px; overflow: auto;
  white-space: pre-wrap; word-break: break-all;
}
</style>
