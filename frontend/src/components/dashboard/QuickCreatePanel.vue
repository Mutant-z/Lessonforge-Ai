<script setup lang="ts">
import { computed, ref } from 'vue';
import { useRouter } from 'vue-router';
import { useAuthStore } from '../../stores/auth';
import { useCourseStore } from '../../stores/courses';
import { useCourseIntakeStore } from '../../stores/courseIntake';
import { ArrowRight, Cpu } from '@element-plus/icons-vue';
import AgentComposer from '../intake/AgentComposer.vue';

const auth = useAuthStore();
const store = useCourseStore();
const intake = useCourseIntakeStore();
const router = useRouter();
const starting = ref(false);
const error = ref('');
const selectedModelConfigId = ref<string | null>(null);

const recentEditedCourse = computed(() => {
  if (!store.items.length) return null;
  return store.items[0];
});

function greetTime() {
  const hr = new Date().getHours();
  if (hr < 12) return '上午好';
  if (hr < 18) return '下午好';
  return '晚上好';
}

async function startIntake(content: string, files: File[]) {
  starting.value = true;
  error.value = '';
  try {
    const session = await intake.create(selectedModelConfigId.value);
    if (files.length) await Promise.allSettled(files.map(file => intake.upload(file)));
    await intake.send(content);
    await router.push({ path: '/courses/new', query: { session: session.id } });
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '无法创建需求会话';
  } finally {
    starting.value = false;
  }
}
</script>

<template>
  <div class="welcome-quick-panel">
    <div class="panel-inner">
      <div class="greeting-row">
        <div class="greeting-left">
          <span class="user-greeting">{{ greetTime() }}，{{ auth.user?.username || '老师' }}</span>
          <span class="agent-tip-pill">
            <span class="live-dot animate-pulse"></span>
            <span>需求 Agent 已就绪</span>
          </span>
        </div>

        <div v-if="recentEditedCourse" class="quick-cta-bar">
          <button 
            type="button"
            class="continue-edit-pill"
            @click="router.push(`/courses/${recentEditedCourse.id}/workspace`)"
          >
            <span>继续：{{ recentEditedCourse.title.length > 12 ? recentEditedCourse.title.slice(0, 12) + '...' : recentEditedCourse.title }}</span>
            <el-icon><ArrowRight /></el-icon>
          </button>
        </div>
      </div>

      <AgentComposer
        compact
        :disabled="starting"
        v-model:model-config-id="selectedModelConfigId"
        placeholder="输入教学主题生成微课，如：高一物理《牛顿第二定律》，时长 15 分钟…"
        :suggestions="['按教材标准生成', '考点复习精讲', '互动实验引导']"
        @send="startIntake"
      />
      <span v-if="error" class="quick-error">{{ error }}</span>
    </div>
  </div>
</template>

<style scoped>
.welcome-quick-panel {
  background: var(--surface-primary);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-card);
  padding: 12px 16px;
  box-shadow: var(--shadow-xs);
  position: relative;
  overflow: hidden;
  height: 100%;
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  justify-content: center;
}

.panel-inner {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.greeting-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.greeting-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.user-greeting {
  font-size: 15.5px;
  font-weight: 900;
  color: var(--color-primary);
}

.agent-tip-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 800;
  color: var(--accent-violet);
  background: var(--accent-violet-soft);
  padding: 3px 10px;
  border-radius: var(--radius-pill);
}

.live-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--accent-violet);
}

.quick-cta-bar {
  display: flex;
  align-items: center;
}

.continue-edit-pill {
  border: 1px solid var(--color-primary-border);
  background: var(--color-primary-soft);
  color: var(--color-primary);
  border-radius: var(--radius-pill);
  padding: 4px 12px;
  font-size: 12.5px;
  font-weight: 700;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  cursor: pointer;
  transition: all var(--motion-fast);
}

.continue-edit-pill:hover {
  background: var(--color-primary);
  color: #ffffff;
}

.quick-error { display: block; margin-top: 4px; color: var(--color-danger); font-size: 12.5px; }

.welcome-quick-panel :deep(.agent-composer) {
  border-radius: var(--radius-control);
  padding: 10px 12px;
  background: var(--surface-secondary);
  border-color: var(--border-default);
}

.welcome-quick-panel :deep(.agent-composer textarea) {
  font-size: 14px;
  min-height: 38px !important;
}

.welcome-quick-panel :deep(.composer-footer) {
  padding-top: 6px;
  border-top-color: var(--border-light);
}

.welcome-quick-panel :deep(.suggestion-row) {
  margin-top: 6px;
}
</style>

