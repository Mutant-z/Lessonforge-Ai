<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue';
import { useRoute } from 'vue-router';
import { useProjectStore } from '../stores/project';
import ProjectShell from '../components/project/ProjectShell.vue';
import OverviewConsoleWorkbench from '../components/project/overview/OverviewConsoleWorkbench.vue';
import ProjectMemoryPanel from '../components/project/ProjectMemoryPanel.vue';
import ErrorState from '../components/feedback/ErrorState.vue';
import { errorMessage } from '../api/client';

const route = useRoute();
const store = useProjectStore();
const courseId = route.params.id as string;
const showMemory = ref(false);
const projectError = ref('');

const deliveryTasks = computed(() => store.tasks.filter(task => task.task_type !== 'video_generation'));
const completion = computed(() => deliveryTasks.value.length ? Math.round(deliveryTasks.value.reduce((sum, task) => sum + task.progress, 0) / deliveryTasks.value.length) : 0);
const approvedCount = computed(() => deliveryTasks.value.filter(task => task.status === 'approved').length);
const activeCount = computed(() => deliveryTasks.value.filter(task => ['queued', 'running'].includes(task.status)).length);
const attentionCount = computed(() => deliveryTasks.value.filter(task => ['failed', 'stale'].includes(task.status)).length);
const reviewCount = computed(() => deliveryTasks.value.filter(task => task.status === 'review').length);

async function loadProject() {
  projectError.value = '';
  try {
    await store.open(courseId);
  } catch (cause) {
    projectError.value = errorMessage(cause);
  }
}

onMounted(loadProject);
onUnmounted(() => store.disconnect());
</script>

<template>
  <div v-if="store.loading && !store.project" class="project-loading">
    <el-skeleton :rows="8" animated />
  </div>

  <div v-else-if="projectError" class="project-error">
    <ErrorState
      title="项目暂时无法打开"
      :error="projectError"
      detail="项目数据加载失败，请稍后重试。"
      @retry="loadProject"
    />
  </div>

  <ProjectShell v-else-if="store.project">
    <div class="overview-scroll-wrap">
      <!-- Unified Single Workbench Card Container -->
      <OverviewConsoleWorkbench
        :project="store.project"
        :completion="completion"
        :approved-count="approvedCount"
        :active-count="activeCount"
        :attention-count="attentionCount"
        :review-count="reviewCount"
        :tasks="deliveryTasks"
        :course-id="courseId"
        @retry-planning="store.retryPlanning(courseId)"
        @initialize-agents="store.initializeAgents(courseId)"
        @open-memory="showMemory = true"
      />
    </div>
    <ProjectMemoryPanel :course-id="courseId" :visible="showMemory" @close="showMemory = false" />
  </ProjectShell>
</template>

<style scoped>
.project-loading {
  padding: 32px;
}

.project-error {
  padding: 32px;
  max-width: 720px;
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
