<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue';
import { useRoute } from 'vue-router';
import { api, errorMessage } from '../api/client';
import { useProjectStore } from '../stores/project';
import ProjectShell from '../components/project/ProjectShell.vue';
import { 
  Download, 
  CircleCheck, 
  Cpu 
} from '@element-plus/icons-vue';

const route = useRoute();
const store = useProjectStore();
const courseId = route.params.id as string;

const items = ref<any[]>([]);
const busy = ref(false);
const result = ref<any>(null);
const error = ref('');
const videoTask = computed(() => store.project?.tasks.find((task) => task.task_type === 'video_generation'));
const videoIncluded = computed(() => videoTask.value?.status === 'approved');

function isIncluded(item: any) {
  return item.artifact_type !== 'video_generation' || item.status === 'approved';
}

async function loadArtifacts() {
  await store.open(courseId);
  const { data } = await api.get(`/courses/${courseId}/artifacts`);
  items.value = data;
}

async function generatePackage() {
  busy.value = true;
  error.value = '';
  try {
    const { data } = await api.post(`/courses/${courseId}/exports`);
    result.value = data;
  } catch (e) {
    error.value = errorMessage(e);
  } finally {
    busy.value = false;
  }
}

async function triggerDownload() {
  if (!result.value) return;
  try {
    const { data } = await api.get(`/exports/${result.value.id}/download`, { responseType: 'blob' });
    const url = URL.createObjectURL(data);
    const a = document.createElement('a');
    a.href = url;
    a.download = result.value.filename || 'lesson_package.zip';
    a.click();
    URL.revokeObjectURL(url);
  } catch (e) {
    error.value = errorMessage(e);
  }
}

onMounted(loadArtifacts);
onUnmounted(() => store.disconnect());

const artifactNames: Record<string, string> = {
  lesson_plan: '教学设计', ppt: 'PPT 课件', task_sheet: '学习任务单', exercise: '课后练习',
  video_script: '视频脚本', video_generation: '微课视频', verbatim: '教师逐字稿', quality_report: '质量报告', citation_report: '引用来源',
};
</script>

<template>
  <ProjectShell v-if="store.project">
    <div class="export-page">
      <header class="export-lead"><span>EXPORT</span><h2>课程交付包</h2><p>将当前确认版本渲染为可编辑的 PPTX、DOCX、质量与引用文件，并生成校验清单。</p></header>
      <div class="export-split-grid">
      <!-- Left Column: Artifacts Selection & Verification Checklist -->
      <div class="export-resources-card lf-card">
        <h3 class="section-title">本次打包文件</h3>
        <div class="resource-items-list">
          <div v-for="item in items" :key="item.id" class="resource-check-row">
            <el-checkbox :model-value="isIncluded(item)" disabled />
            <div class="res-info">
              <span class="res-title">{{ artifactNames[item.artifact_type] || item.artifact_type }}</span>
              <span class="res-sub">V{{ item.version }} · 当前项目版本</span>
            </div>
            <span class="resource-status">{{ isIncluded(item) ? (item.status === 'approved' ? '已确认' : '当前版本') : '审核后加入' }}</span>
          </div>
        </div>
      </div>

      <!-- Right Column: Export Trigger & Manifest Info -->
      <aside class="export-actions-aside lf-card">
        <h3 class="section-title">完整微课交付 ZIP</h3>
        <p class="aside-desc">
          包含可编辑 PPTX、教学文档、学生版与教师版练习、质量报告、引用来源和 SHA256 校验清单；已审核视频会一并打包。
        </p>

        <div class="meta-spec-list">
          <div class="spec-item">
            <span>包含了资源组件:</span>
            <strong>{{ items.length }} 个文件产物</strong>
          </div>
          <div class="spec-item">
            <span>打包交付格式:</span>
            <strong>PPTX / DOCX / MD / MP4 / ZIP</strong>
          </div>
          <div class="spec-item">
            <span>内部规划:</span>
            <strong>已通过结构校验</strong>
          </div>
        </div>

        <el-alert
          v-if="videoTask && !videoIncluded"
          type="warning"
          title="视频任务尚未完成或未审核，本次仍可正常导出其他课程资源。"
          :closable="false"
          show-icon
          class="video-export-alert"
        />

        <el-alert v-if="error" type="error" :title="error" show-icon class="error-alert" />

        <div class="export-button-zone">
          <el-button 
            v-if="!result" 
            type="primary" 
            size="large" 
            class="full-width-btn" 
            :loading="busy" 
            :icon="Cpu" 
            @click="generatePackage"
          >
            {{ busy ? '正在渲染与校验完整资源包...' : '生成完整课程包 ZIP' }}
          </el-button>

          <div v-else class="download-ready-box animate-fade-in">
            <div class="ready-banner">
              <el-icon class="ready-icon"><CircleCheck /></el-icon>
              <div>
                <strong>资源包已装配并通过 ZIP 完整性校验</strong>
                <span>{{ result.filename }} · {{ (result.size_bytes / 1024 / 1024).toFixed(2) }} MB</span>
              </div>
            </div>

            <el-button 
              type="success" 
              size="large" 
              class="full-width-btn" 
              :icon="Download" 
              @click="triggerDownload"
            >
              立即下载课程 ZIP 资源包
            </el-button>
          </div>
        </div>
      </aside>
      </div>
    </div>
  </ProjectShell>
</template>

<style scoped>
.export-page { height: 100%; overflow-y: auto; padding: 26px 30px 36px; box-sizing: border-box; background: #f7f7f8; }
.export-lead { padding-bottom: 22px; border-bottom: 1px solid #cfd2d9; margin-bottom: 22px; }
.export-lead > span { color: #002fa7; font-size: 11px; font-weight: 800; letter-spacing: .08em; }
.export-lead h2 { margin: 8px 0 5px; font-size: 34px; letter-spacing: -.03em; }
.export-lead p { margin: 0; color: #656a73; font-size: 13px; }
.export-split-grid {
  display: grid;
  grid-template-columns: 1.2fr 0.8fr;
  gap: 24px;
}
.export-resources-card, .export-actions-aside { background: #fff; border: 1px solid #cfd2d9; padding: 20px; box-shadow: none; border-radius: 0; }

@media (max-width: 960px) {
  .export-split-grid {
    grid-template-columns: 1fr;
  }
}

.section-title {
  margin: 0 0 16px;
  font-size: 16px;
  font-weight: 800;
  color: var(--text-primary);
  padding-bottom: 10px;
  border-bottom: 1px solid var(--border-light);
}

.resource-items-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.resource-check-row {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 12px 16px;
  background: var(--bg-page);
  border: 1px solid var(--border-default);
  border-radius: 0;
}

.res-info {
  flex: 1;
  display: flex;
  flex-direction: column;
}

.res-title {
  font-size: 15px;
  font-weight: 700;
  color: var(--text-primary);
}

.res-sub {
  font-size: 12.5px;
  color: var(--text-muted);
}

.aside-desc {
  font-size: 14px;
  line-height: 1.6;
  color: var(--text-secondary);
  margin-bottom: 20px;
}

.meta-spec-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 16px 18px;
  background: #f7f7f8;
  border-radius: 0;
  margin-bottom: 24px;
}

.spec-item {
  display: flex;
  justify-content: space-between;
  font-size: 13px;
  color: var(--text-muted);
}

.spec-item strong {
  color: var(--text-primary);
}

.full-width-btn {
  width: 100%;
}

.video-export-alert { margin: 0 0 18px; border-radius: 0; }

.ready-banner {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 16px;
  background: var(--color-success-soft);
  color: var(--color-success);
  border-radius: 0;
  margin-bottom: 16px;
}

.ready-icon {
  font-size: 26px;
}

.ready-banner strong {
  display: block;
  font-size: 15px;
}

.ready-banner span {
  font-size: 12.5px;
}
.resource-status { color: #002fa7; font-size: 12px; font-weight: 700; }
@media (max-width: 640px) { .export-page { padding: 18px 14px 28px; } }
</style>
