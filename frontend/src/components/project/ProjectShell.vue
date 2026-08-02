<script setup lang="ts">
import { Download, House, Link } from '@element-plus/icons-vue';
import { useRouter } from 'vue-router';
import { useProjectStore } from '../../stores/project';
import ProjectTaskRail from './ProjectTaskRail.vue';

defineProps<{ activeType?: string }>();
const router = useRouter();
const store = useProjectStore();
</script>

<template>
  <section v-if="store.project" class="project-shell">
    <header class="project-header">
      <div class="project-heading">
        <button type="button" class="back-button" @click="router.push('/')">
          <el-icon><House /></el-icon><span>项目库</span>
        </button>
        <div class="project-title">
          <h1>{{ store.project.course.title }}</h1>
          <span>{{ store.project.course.subject }} · {{ store.project.course.grade_level }} · {{ store.project.course.duration_minutes }} 分钟</span>
        </div>
      </div>
      <div class="project-actions">
        <span v-if="store.connectionError" class="connection-warning"><el-icon><Link /></el-icon>{{ store.connectionError }}</span>
        <span v-else class="connection-state"><el-icon><Link /></el-icon>项目状态实时同步</span>
        <el-button type="primary" :icon="Download" @click="router.push(`/courses/${store.project.course.id}/export`)">导出课程</el-button>
      </div>
    </header>
    <div class="rail-viewport">
      <ProjectTaskRail :course-id="store.project.course.id" :tasks="store.tasks" :active-type="activeType" />
    </div>
    <main class="project-content"><slot /></main>
  </section>
</template>

<style scoped>
.project-shell {
  --project-blue: #002fa7;
  height: calc(100dvh - var(--header-height));
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: #f7f7f8;
  color: #18191d;
  font-family: "Helvetica Neue", Helvetica, Arial, "PingFang SC", sans-serif;
}

.project-header {
  min-height: 66px;
  padding: 0 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  background: #fff;
}

.project-heading, .project-actions { display: flex; align-items: center; gap: 18px; min-width: 0; }
.back-button { border: 0; background: transparent; padding: 8px 0; display: flex; gap: 6px; align-items: center; color: #51545b; cursor: pointer; }
.project-title { min-width: 0; padding-left: 18px; border-left: 1px solid #d9dce3; }
.project-title h1 { margin: 0; font-size: 19px; line-height: 1.2; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.project-title span { display: block; margin-top: 3px; font-size: 12px; color: #656a73; }
.connection-state, .connection-warning { display: flex; align-items: center; gap: 5px; font-size: 12px; color: #656a73; }
.connection-warning { color: #b42318; }
.rail-viewport { flex: 0 0 auto; overflow-x: auto; scrollbar-width: thin; }
.project-content { flex: 1; min-height: 0; overflow: hidden; }
.project-shell :deep(.el-button--primary) { background: #002fa7 !important; border-color: #002fa7 !important; border-radius: 0 !important; box-shadow: none !important; }

@media (max-width: 900px) {
  .project-header { padding: 0 14px; }
  .project-actions > span { display: none; }
  .project-title span { display: none; }
  .back-button span { display: none; }
}
</style>
