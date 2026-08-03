<script setup lang="ts">
import { computed, onMounted, onUnmounted } from 'vue';
import { useRoute } from 'vue-router';
import { useProjectStore } from '../stores/project';
import ProjectShell from '../components/project/ProjectShell.vue';
import OverviewConsoleWorkbench from '../components/project/overview/OverviewConsoleWorkbench.vue';

const route = useRoute();
const store = useProjectStore();
const courseId = route.params.id as string;

const approvedCount = computed(() => store.tasks.filter(task => task.status === 'approved').length);
const activeCount = computed(() => store.tasks.filter(task => ['queued', 'running'].includes(task.status)).length);
const attentionCount = computed(() => store.tasks.filter(task => ['failed', 'stale'].includes(task.status)).length);
const reviewCount = computed(() => store.tasks.filter(task => task.status === 'review').length);

onMounted(() => store.open(courseId));
onUnmounted(() => store.disconnect());
</script>

<template>
  <div v-if="store.loading && !store.project" class="project-loading">
    <el-skeleton :rows="8" animated />
  </div>

  <ProjectShell v-else-if="store.project">
    <div class="overview-scroll-wrap">
      <!-- Unified Single Workbench Card Container -->
      <OverviewConsoleWorkbench
        :project="store.project"
        :completion="store.completion"
        :approved-count="approvedCount"
        :active-count="activeCount"
        :attention-count="attentionCount"
        :review-count="reviewCount"
        :tasks="store.tasks"
        :course-id="courseId"
        @retry-planning="store.retryPlanning(courseId)"
        @initialize-agents="store.initializeAgents(courseId)"
      />
    </div>
  </ProjectShell>
</template>

<style scoped>
.project-loading {
  padding: 32px;
}

.overview-scroll-wrap {
  height: 100%;
  overflow-y: auto;
  padding: 20px 24px 36px;
  box-sizing: border-box;
}

.overview-scroll-wrap::-webkit-scrollbar {
  width: 6px;
}
.overview-scroll-wrap::-webkit-scrollbar-thumb {
  background: #cbd5e1;
  border-radius: 999px;
}
.overview-scroll-wrap::-webkit-scrollbar-track {
  background: transparent;
}

@media (max-width: 640px) {
  .overview-scroll-wrap {
    padding: 12px 12px 24px;
  }
}
</style>
