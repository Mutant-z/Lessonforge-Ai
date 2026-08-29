<script setup lang="ts">
import { computed, ref } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import { Check, Delete, Download, House, Link } from '@element-plus/icons-vue';
import { useRouter } from 'vue-router';
import { errorMessage } from '../../api/client';
import { useCourseStore } from '../../stores/courses';
import { useProjectStore } from '../../stores/project';
import ProjectTaskRail from './ProjectTaskRail.vue';

const props = defineProps<{ activeType?: string; compact?: boolean }>();
const router = useRouter();
const courses = useCourseStore();
const store = useProjectStore();
const deleting = ref(false);

const isCompactMode = computed(() => props.compact || props.activeType === 'ppt');
const deliveryTasks = computed(() => store.tasks.filter(task => task.task_type !== 'video_generation'));

async function handleDeleteProject() {
  const course = store.project?.course;
  if (!course || deleting.value) return;

  try {
    await ElMessageBox.confirm(
      `确定要删除项目“${course.title}”吗？删除后项目将从项目库中移除，生成内容也将无法继续访问。`,
      '删除微课项目',
      {
        confirmButtonText: '确定删除',
        cancelButtonText: '取消',
        distinguishCancelAndClose: true,
        type: 'warning',
      },
    );
  } catch {
    return;
  }

  deleting.value = true;
  try {
    await courses.delete(course.id);
    store.disconnect();
    store.project = null;
    store.currentTask = null;
    ElMessage.success('项目已删除');
    await router.replace('/');
  } catch (cause) {
    ElMessage.error(errorMessage(cause));
  } finally {
    deleting.value = false;
  }
}
</script>

<template>
  <section v-if="store.project" class="project-shell" :class="{ compact: isCompactMode }">
    <header class="workspace-top-bar" :class="{ 'compact-top-bar': isCompactMode }">
      <!-- Tier 1: Course Info & Actions Bar -->
      <div class="workspace-meta-row">
        <div class="meta-left">
          <button type="button" class="back-pill-btn" @click="router.push('/')">
            <el-icon><House /></el-icon><span>项目库</span>
          </button>
          <div class="course-heading-box">
            <h1>{{ store.project.course.title }}</h1>
            <span class="course-spec-badge">{{ store.project.course.subject }} · {{ store.project.course.grade_level }} · {{ store.project.course.duration_minutes }} 分钟</span>
          </div>
        </div>

        <div class="meta-right">
          <span v-if="store.connectionError" class="sync-status warning"><el-icon><Link /></el-icon>{{ store.connectionError }}</span>
          <span v-else class="sync-status success"><el-icon><Check /></el-icon>实时同步</span>
          <el-button
            class="delete-project-action"
            type="danger"
            plain
            size="small"
            :icon="Delete"
            :loading="deleting"
            @click="handleDeleteProject"
          >删除项目</el-button>
          <el-button type="primary" size="small" :icon="Download" @click="router.push(`/courses/${store.project.course.id}/export`)">导出课程</el-button>
        </div>
      </div>

      <!-- Tier 2: Task Navigation Rail Bar -->
      <div class="workspace-rail-row">
        <ProjectTaskRail :course-id="store.project.course.id" :tasks="deliveryTasks" :active-type="activeType" />
      </div>
    </header>

    <main class="project-content"><slot /></main>
  </section>
</template>

<style scoped>
.project-shell {
  --project-blue: var(--primary-600, #4f46e5);
  height: calc(100dvh - var(--header-height, 52px));
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: #f8fafc;
  color: var(--text-primary, #0f172a);
  font-family: -apple-system, BlinkMacSystemFont, "Inter", "Segoe UI", sans-serif;
}

.workspace-top-bar {
  background: #ffffff;
  border-bottom: 1px solid var(--border-default, #e2e8f0);
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.02);
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 8px 20px 6px;
  flex-shrink: 0;
  transition: all 200ms ease;
}

.workspace-top-bar.compact-top-bar {
  padding: 5px 16px 5px;
  gap: 4px;
}

.workspace-meta-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  width: 100%;
}

.meta-left, .meta-right {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.back-pill-btn {
  border: 1px solid var(--border-default, #e2e8f0);
  background: #f8fafc;
  padding: 3px 10px;
  border-radius: var(--radius-pill, 999px);
  display: inline-flex;
  gap: 4px;
  align-items: center;
  color: var(--text-secondary, #334155);
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
  white-space: nowrap;
  transition: all var(--motion-fast, 150ms);
}

.back-pill-btn:hover {
  background: var(--primary-50, #eef2ff);
  color: var(--primary-700, #4338ca);
  border-color: var(--primary-200, #c7d2fe);
}

.course-heading-box {
  min-width: 0;
  padding-left: 10px;
  border-left: 1px solid #e2e8f0;
  display: flex;
  align-items: center;
  gap: 8px;
}

.course-heading-box h1 {
  margin: 0;
  font-size: 14px;
  font-weight: 800;
  line-height: 1.2;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  color: var(--text-primary, #0f172a);
}

.course-spec-badge {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-muted, #64748b);
  background: #f1f5f9;
  padding: 2px 8px;
  border-radius: 999px;
  white-space: nowrap;
  flex-shrink: 0;
}

.sync-status {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  font-weight: 600;
  color: var(--accent-mint, #059669);
  background: #ecfdf5;
  border: 1px solid #a7f3d0;
  padding: 2px 8px;
  border-radius: var(--radius-pill, 999px);
  white-space: nowrap;
}

.sync-status.warning {
  color: #b91c1c;
  background: #fff1f2;
  border-color: #fecdd3;
}

.workspace-rail-row {
  width: 100%;
  overflow-x: auto;
  scrollbar-width: none;
}

.workspace-rail-row::-webkit-scrollbar {
  display: none;
}

.project-content {
  flex: 1;
  min-height: 0;
  overflow: hidden;
  position: relative;
}

.delete-project-action {
  border-radius: var(--radius-pill, 999px) !important;
  font-weight: 700 !important;
  transition: all 200ms ease !important;
}

.delete-project-action:hover {
  transform: translateY(-1px);
}

.project-shell :deep(.el-button--primary) {
  background: linear-gradient(135deg, var(--primary-600, #4f46e5) 0%, var(--accent-violet, #7c3aed) 100%) !important;
  border: 0 !important;
  border-radius: var(--radius-pill, 999px) !important;
  font-weight: 700 !important;
  box-shadow: 0 2px 8px rgba(79, 70, 229, 0.2) !important;
  transition: all 200ms ease !important;
}

.project-shell :deep(.el-button--primary:hover) {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(79, 70, 229, 0.3) !important;
}

@media (max-width: 900px) {
  .workspace-top-bar { padding: 4px 12px; }
  .meta-right > span { display: none; }
  .course-spec-badge { display: none; }
  .back-pill-btn span { display: none; }
}
</style>
