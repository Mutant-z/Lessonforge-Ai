<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { api, errorMessage } from '../api/client';
import { useCourseStore } from '../stores/courses';
import PageHeader from '../components/layout/PageHeader.vue';
import JsonTreeRenderer from '../components/content-renderers/JsonTreeRenderer.vue';
import QualityIssueCard from '../components/domain/QualityIssueCard.vue';
import CitationCard from '../components/content-renderers/CitationCard.vue';
import { 
  FolderChecked, 
  CircleCheck, 
  Connection, 
  Edit, 
  View,
  Refresh 
} from '@element-plus/icons-vue';

const route = useRoute();
const router = useRouter();
const store = useCourseStore();

const bp = ref<any>(null);
const loading = ref(true);
const saving = ref(false);
const error = ref('');
const activeTab = ref('objectives');
const mode = ref<'visual' | 'json'>('visual');

const sections = [
  ['course_identity', '课程基本属性'],
  ['learning_analysis', '学情分析总结'],
  ['objectives', '观察化教学目标'],
  ['knowledge_points', '知识点结构表'],
  ['timeline', '分时教学时间线'],
  ['assessment_plan', '教学评价计划'],
  ['terminology', '核心术语清单'],
  ['resource_constraints', '资源生成约束']
];

const jsonContent = computed({
  get: () => JSON.stringify(bp.value?.content_json?.[activeTab.value], null, 2),
  set: (val) => {
    try {
      bp.value.content_json[activeTab.value] = JSON.parse(val);
      error.value = '';
    } catch {
      error.value = '当前 JSON 格式有误';
    }
  }
});

async function load() {
  loading.value = true;
  error.value = '';
  try {
    await store.open(route.params.id as string);
    const { data } = await api.get(`/courses/${route.params.id}/blueprints`);
    if (data && data.length) {
      bp.value = { ...data[0], content_json: data[0].content_json || data[0].content };
    } else {
      error.value = '未找到该课程的蓝图信息，请重新生成或启动';
    }
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    loading.value = false;
  }
}

async function saveVersion() {
  saving.value = true;
  try {
    const { data } = await api.patch(`/blueprints/${bp.value.id}`, {
      content: bp.value.content_json,
      change_summary: '教师编辑确认蓝图'
    });
    bp.value = { ...data, content_json: data.content_json || data.content };
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    saving.value = false;
  }
}

async function approveAndStart() {
  try {
    await api.post(`/blueprints/${bp.value.id}/approve`);
    const { data: run } = await api.post(`/courses/${route.params.id}/generations`);
    router.push(`/courses/${route.params.id}/generation/${run.id}`);
  } catch (e) {
    error.value = errorMessage(e);
  }
}

onMounted(load);
</script>

<template>
  <div class="blueprint-root-view">
    <div v-if="bp" class="blueprint-workspace-container animate-fade-in">
      <PageHeader 
        :eyebrow="`02 / 课程蓝图 · Version ${bp.version}`" 
        :title="store.current?.title || '课程蓝图确认'"
        subtitle="确认蓝图作为多 Agent 生产全局唯一的“事实源 (Single Source of Truth)”"
      >
        <template #actions>
          <el-button size="large" :icon="FolderChecked" :loading="saving" @click="saveVersion">
            保存新版本
          </el-button>
          <el-button type="primary" size="large" :icon="CircleCheck" @click="approveAndStart">
            确认蓝图并生成资源
          </el-button>
        </template>
      </PageHeader>

      <div class="blueprint-3col-layout">
        <!-- Left Column: Section Nav -->
        <aside class="sections-nav-panel lf-card">
          <h4 class="panel-title">蓝图章节</h4>
          <nav class="nav-menu">
            <button 
              v-for="([key, label], idx) in sections" 
              :key="key" 
              class="section-btn"
              :class="{ active: activeTab === key }"
              @click="activeTab = key"
            >
              <span class="btn-num">0{{ idx + 1 }}</span>
              <span class="btn-label">{{ label }}</span>
            </button>
          </nav>
        </aside>

        <!-- Middle Column: Visual & JSON Editor -->
        <main class="editor-main-panel lf-card">
          <div class="editor-top-bar">
            <div class="editor-title-group">
              <h3>{{ sections.find(x => x[0] === activeTab)?.[1] }}</h3>
              <span class="edit-mode-badge">{{ mode === 'visual' ? '结构化视图' : 'JSON 源码编辑' }}</span>
            </div>

            <el-radio-group v-model="mode" size="default">
              <el-radio-button value="visual">
                <el-icon><View /></el-icon> 结构化
              </el-radio-button>
              <el-radio-button value="json">
                <el-icon><Edit /></el-icon> JSON 源码
              </el-radio-button>
            </el-radio-group>
          </div>

          <div class="editor-content-body">
            <div v-if="mode === 'visual'" class="visual-view-wrapper">
              <JsonTreeRenderer :content="bp.content_json[activeTab]" />
            </div>
            <div v-else class="json-code-textarea-wrapper">
              <textarea v-model="jsonContent" class="json-raw-textarea" spellcheck="false"></textarea>
            </div>
            <p v-if="error" class="error-msg">{{ error }}</p>
          </div>
        </main>

        <!-- Right Column: AI Suggestions, Quality Issues, Citations -->
        <aside class="auxiliary-info-panel lf-card">
          <!-- AI Advice Box -->
          <div class="side-widget">
            <h4>💡 AI 设计建议</h4>
            <p class="advice-text">
              课程蓝图是全部教学材料的底座。请重点核查教学目标是否使用“理解、撰写、计算”等可观察动词。
            </p>
          </div>

          <!-- Rule Check Issues -->
          <div class="side-widget">
            <h4>📋 结构化校验结果</h4>
            <div v-if="!bp.issues?.length" class="ok-alert">
              <el-icon><CircleCheck /></el-icon> 未发现合规性校验缺陷
            </div>
            <div v-else class="issues-list">
              <QualityIssueCard 
                v-for="issue in bp.issues" 
                :key="issue.id" 
                :issue="issue" 
              />
            </div>
          </div>

          <!-- Citation Source References -->
          <div class="side-widget">
            <h4><el-icon><Connection /></el-icon> 参考材料引用</h4>
            <div v-if="!bp.content_json?.source_refs?.length" class="empty-sources">
              未引用外部上传材料
            </div>
            <div v-else class="sources-list">
              <CitationCard 
                v-for="(refItem, rIdx) in bp.content_json.source_refs" 
                :key="rIdx" 
                :source-name="refItem" 
                :is-uploaded-material="true" 
              />
            </div>
          </div>
        </aside>
      </div>
    </div>

    <div v-else-if="loading" class="page-container animate-fade-in" style="padding: 40px;">
      <el-skeleton :rows="8" animated />
    </div>

    <div v-else class="page-container animate-fade-in" style="padding: 40px; text-align: center;">
      <el-alert type="warning" :title="error || '蓝图数据暂未生成'" show-icon style="margin-bottom: 20px" />
      <el-button type="primary" :icon="Refresh" @click="load">重试加载蓝图</el-button>
    </div>
  </div>
</template>

<style scoped>
.blueprint-root-view {
  height: 100%;
  width: 100%;
  overflow-y: auto;
}

.blueprint-workspace-container {
  padding: 32px 36px 60px;
}

.blueprint-3col-layout {
  display: grid;
  grid-template-columns: 240px 1fr 340px;
  gap: 24px;
  min-height: 700px;
}

@media (max-width: 1280px) {
  .blueprint-3col-layout {
    grid-template-columns: 200px 1fr 300px;
  }
}

@media (max-width: 1024px) {
  .blueprint-3col-layout {
    grid-template-columns: 1fr;
  }
}

.panel-title {
  margin: 0 0 18px;
  font-size: 16.5px;
  font-weight: 800;
  color: var(--text-primary);
  border-bottom: 1px solid var(--border-light);
  padding-bottom: 10px;
}

.nav-menu {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.section-btn {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 13px 16px;
  border: 0;
  background: transparent;
  border-radius: var(--radius-md);
  text-align: left;
  cursor: pointer;
  color: var(--text-secondary);
  transition: all var(--motion-fast);
}

.section-btn:hover {
  background: var(--bg-subtle);
  color: var(--text-primary);
}

.section-btn.active {
  background: var(--color-primary-soft);
  color: var(--color-primary);
  font-weight: 800;
}

.btn-num {
  font-size: 13px;
  font-weight: 900;
  color: var(--color-primary);
}

.btn-label {
  font-size: 15px;
}

.editor-main-panel {
  display: flex;
  flex-direction: column;
}

.editor-top-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 18px;
  padding-bottom: 14px;
  border-bottom: 1px solid var(--border-light);
}

.editor-title-group {
  display: flex;
  align-items: center;
  gap: 14px;
}

.editor-title-group h3 {
  margin: 0;
  font-size: 20px;
  font-weight: 900;
  color: var(--text-primary);
}

.edit-mode-badge {
  font-size: 13.5px;
  color: var(--text-muted);
  background: var(--bg-subtle);
  padding: 4px 12px;
  border-radius: var(--radius-xs);
  font-weight: 600;
}

.editor-content-body {
  flex: 1;
  display: flex;
  flex-direction: column;
  font-size: 15.5px;
}

.json-raw-textarea {
  width: 100%;
  height: 520px;
  padding: 18px;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  font-family: SFMono-Regular, Consolas, monospace;
  font-size: 15px;
  line-height: 1.7;
  outline: none;
  resize: vertical;
}

.json-raw-textarea:focus {
  border-color: var(--color-primary);
}

.error-msg {
  color: var(--color-danger);
  font-size: 14.5px;
  margin-top: 10px;
}

.side-widget {
  margin-bottom: 26px;
}

.side-widget h4 {
  margin: 0 0 12px;
  font-size: 16px;
  font-weight: 800;
  color: var(--text-primary);
  display: flex;
  align-items: center;
  gap: 8px;
}

.advice-text {
  font-size: 14.5px;
  line-height: 1.65;
  color: var(--text-secondary);
  background: var(--bg-page);
  padding: 14px;
  border-radius: var(--radius-md);
  margin: 0;
}

.ok-alert {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 16px;
  background: var(--color-success-soft);
  color: var(--color-success);
  border-radius: var(--radius-md);
  font-size: 14.5px;
  font-weight: 700;
}

.empty-sources {
  font-size: 13.5px;
  color: var(--text-muted);
}
</style>

