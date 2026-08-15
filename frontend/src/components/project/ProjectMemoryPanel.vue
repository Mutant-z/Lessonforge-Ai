<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { ArrowDown, Memo, RefreshRight, Search } from '@element-plus/icons-vue';
import type { MemoryItem } from '../../types';
import { memoryApi } from '../../api/memory';

const props = defineProps<{ courseId: string; visible: boolean }>();
const emit = defineEmits<{ (e: 'close'): void }>();

const loading = ref(false);
const error = ref('');
const revision = ref(0);
const groups = ref<Record<string, MemoryItem[]>>({});
const query = ref('');
const searching = ref(false);
const searchResults = ref<MemoryItem[]>([]);
const expanded = ref<Record<string, boolean>>({});

const SOURCE_LABELS: Record<string, string> = {
  requirement: '课程需求',
  blueprint: '课程蓝图',
  material: '上传材料',
  artifact: 'Agent 产物',
  decision: '教师决策',
  qa: 'QA 结论',
  dialogue: '对话摘要',
};

const ARTIFACT_LABELS: Record<string, string> = {
  lesson_plan: '教学设计',
  ppt: 'PPT 课件',
  task_sheet: '学习任务单',
  exercise: '课后练习',
  video_script: '视频脚本',
  verbatim: '教师逐字稿',
};

const groupEntries = computed(() =>
  Object.entries(groups.value)
    .filter(([, items]) => items.length > 0)
    .sort((a, b) => a[0].localeCompare(b[0])),
);

const totalCount = computed(() =>
  Object.values(groups.value).reduce((sum, items) => sum + items.length, 0),
);

function labelFor(item: MemoryItem): string {
  if (item.artifact_type) return ARTIFACT_LABELS[item.artifact_type] || item.artifact_type;
  return SOURCE_LABELS[item.source_type] || item.source_type;
}

function trustLabel(item: MemoryItem): string {
  const map: Record<string, string> = {
    teacher_requirement: '教师要求',
    approved_blueprint: '已确认蓝图',
    uploaded_material: '上传材料',
    agent_generated: 'Agent 生成',
    teacher_decision: '教师决策',
    qa_result: 'QA 结果',
  };
  return map[item.trust_level || ''] || item.trust_level || '';
}

function artifactName(item: MemoryItem): string {
  const summary = item.summary || {};
  if (item.source_type === 'material') return summary.original_filename || '材料';
  if (item.source_type === 'blueprint') return `蓝图 V${item.source_version}`;
  if (item.source_type === 'decision') return summary.title || '教师决策';
  if (item.source_type === 'qa') return `QA ${summary.score ?? ''} 分`;
  return `${labelFor(item)} V${item.source_version}`;
}

function artifactDetail(item: MemoryItem): string {
  const summary = item.summary || {};
  if (item.source_type === 'material') return summary.summary || '';
  if (item.source_type === 'qa') return summary.summary || '';
  if (item.source_type === 'blueprint') {
    const identity = summary.course_identity || {};
    return `${identity.title || ''} · ${(summary.objectives || []).length} 个目标 · ${(summary.knowledge_points || []).length} 个知识点`;
  }
  if (item.source_type === 'decision') return summary.detail || '';
  if (item.source_type === 'artifact') return item.summary?.truncated ? '内容较多，已压缩索引（可在 Agent 工作台查看完整文件）' : '';
  return '';
}

function toggleExpanded(key: string) {
  expanded.value[key] = !expanded.value[key];
}

function isExpanded(item: MemoryItem): boolean {
  return Boolean(expanded.value[`${item.source_type}:${item.source_id}`]);
}

async function load() {
  if (!props.courseId) return;
  loading.value = true;
  error.value = '';
  try {
    const data = await memoryApi.get(props.courseId);
    revision.value = data.revision;
    groups.value = data.items || {};
    query.value = '';
    searchResults.value = [];
  } catch (cause: any) {
    error.value = cause?.message || '项目记忆加载失败';
  } finally {
    loading.value = false;
  }
}

async function doSearch() {
  const q = query.value.trim();
  if (!q) {
    searchResults.value = [];
    return;
  }
  searching.value = true;
  try {
    const data = await memoryApi.search(props.courseId, q);
    searchResults.value = data.items || [];
  } catch (cause: any) {
    error.value = cause?.message || '检索失败';
  } finally {
    searching.value = false;
  }
}

watch(() => props.visible, visible => {
  if (visible) void load();
});
</script>

<template>
  <el-drawer
    :model-value="visible"
    :size="'520px'"
    :title="'共享项目记忆'"
    class="project-memory-drawer"
    @close="emit('close')"
    @closed="emit('close')"
  >
    <div class="memory-panel">
      <div class="memory-header">
        <div class="memory-rev-badge">
          <el-icon><Memo /></el-icon>
          <strong>当前记忆版本 V{{ revision }}</strong>
          <span>{{ totalCount }} 条索引</span>
        </div>
        <el-button size="small" :icon="RefreshRight" :loading="loading" @click="load">刷新</el-button>
      </div>
      <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" style="margin-bottom: 12px" />

      <div class="memory-search">
        <el-input
          v-model="query"
          placeholder="搜索需求、材料、产物、决策…"
          clearable
          :prefix-icon="Search"
          @keyup.enter="doSearch"
          @clear="searchResults = []"
        >
          <template #append>
            <el-button :loading="searching" @click="doSearch">搜索</el-button>
          </template>
        </el-input>
      </div>

      <!-- Search results -->
      <div v-if="searchResults.length" class="memory-group">
        <h4>检索结果（{{ searchResults.length }}）</h4>
        <div v-for="item in searchResults" :key="item.id" class="memory-card">
          <div class="memory-card-head">
            <span class="memory-kind">{{ labelFor(item) }}</span>
            <span class="memory-trust">{{ trustLabel(item) }}</span>
          </div>
          <strong class="memory-name">{{ artifactName(item) }}</strong>
          <p class="memory-detail">{{ artifactDetail(item) || (item.summary?.summary || '') }}</p>
          <small class="memory-meta">记忆 V{{ item.memory_revision }} · {{ item.content_ref }}</small>
        </div>
      </div>

      <div v-else class="memory-groups">
        <div v-for="[type, items] in groupEntries" :key="type" class="memory-group">
          <h4>{{ SOURCE_LABELS[type] || type }}（{{ items.length }}）</h4>
          <div v-for="item in items" :key="item.id" class="memory-card" @click="toggleExpanded(item.id)">
            <div class="memory-card-head">
              <span class="memory-kind">{{ labelFor(item) }}</span>
              <span class="memory-trust">{{ trustLabel(item) }}</span>
              <el-icon v-if="isExpanded(item)" class="memory-arrow rotated"><ArrowDown /></el-icon>
              <el-icon v-else class="memory-arrow"><ArrowDown /></el-icon>
            </div>
            <strong class="memory-name">{{ artifactName(item) }}</strong>
            <p class="memory-detail">{{ artifactDetail(item) }}</p>
            <small class="memory-meta">记忆 V{{ item.memory_revision }} · {{ item.content_ref }}</small>
            <div v-if="isExpanded(item)" class="memory-expanded">
              <pre v-if="Object.keys(item.summary || {}).length">{{ JSON.stringify(item.summary, null, 2).slice(0, 1600) }}</pre>
              <span v-else class="memory-empty-note">该条目暂无摘要内容（原始文件可在对应 Agent 工作台查看）。</span>
            </div>
          </div>
        </div>
        <el-empty v-if="!loading && !totalCount" description="项目记忆尚未建立" :image-size="80" />
      </div>

      <p class="memory-note">
        项目记忆是需求、蓝图、材料、各 Agent 产物、教师决策与 QA 结论的结构化索引。原始大文件请到对应 Agent 工作台查看；记忆面板只读，修改产物请进入各自工作区。
      </p>
    </div>
  </el-drawer>
</template>

<style scoped>
.memory-panel { display: flex; flex-direction: column; gap: 12px; }
.memory-header { display: flex; align-items: center; justify-content: space-between; }
.memory-rev-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: #7c3aed;
  background: #f5f3ff;
  border: 1px solid #ddd6fe;
  padding: 4px 12px;
  border-radius: 999px;
}
.memory-rev-badge span { font-size: 11px; color: #6d28d9; opacity: 0.85; }
.memory-search { margin-bottom: 4px; }
.memory-groups { display: flex; flex-direction: column; gap: 14px; max-height: 62vh; overflow-y: auto; padding-right: 4px; }
.memory-group h4 { margin: 0 0 6px; font-size: 13px; font-weight: 800; color: #334155; }
.memory-card {
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 10px 12px;
  margin-bottom: 8px;
  background: #f8fafc;
  cursor: pointer;
  transition: all 150ms ease;
}
.memory-card:hover { background: #ffffff; border-color: #c7d2fe; }
.memory-card-head { display: flex; align-items: center; gap: 6px; margin-bottom: 4px; }
.memory-kind { font-size: 11px; font-weight: 800; color: #4338ca; background: #eef2ff; border: 1px solid #c7d2fe; padding: 1px 7px; border-radius: 999px; }
.memory-trust { font-size: 10.5px; font-weight: 700; color: #047857; background: #ecfdf5; border: 1px solid #a7f3d0; padding: 1px 6px; border-radius: 999px; }
.memory-name { display: block; font-size: 13.5px; font-weight: 800; color: #0f172a; }
.memory-detail { margin: 3px 0 0; font-size: 12px; color: #64748b; line-height: 1.5; word-break: break-all; }
.memory-meta { font-size: 10.5px; color: #94a3b8; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
.memory-expanded { margin-top: 8px; border-top: 1px dashed #cbd5e1; padding-top: 8px; }
.memory-expanded pre { margin: 0; font-size: 11px; line-height: 1.5; color: #334155; white-space: pre-wrap; word-break: break-all; max-height: 240px; overflow-y: auto; background: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 8px; }
.memory-empty-note { font-size: 12px; color: #94a3b8; }
.memory-arrow { font-size: 12px; color: #94a3b8; margin-left: auto; transition: transform 150ms ease; }
.memory-arrow.rotated { transform: rotate(180deg); }
.memory-note { font-size: 11.5px; color: #94a3b8; line-height: 1.5; border-top: 1px solid #f1f5f9; padding-top: 10px; margin: 0; }
</style>
