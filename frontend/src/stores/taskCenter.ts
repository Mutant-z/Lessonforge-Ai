import { defineStore } from 'pinia';
import { ref, computed } from 'vue';
import type { GenerationTask } from '../types';

export const useTaskCenterStore = defineStore('taskCenter', () => {
  const activeTasks = ref<GenerationTask[]>([]);
  const isDrawerOpen = ref(false);

  const runningCount = computed(() => 
    activeTasks.value.filter(t => ['queued', 'running'].includes(t.status)).length
  );

  const waitingReviewCount = computed(() =>
    activeTasks.value.filter(t => t.status === 'waiting_human').length
  );

  function addTask(task: GenerationTask) {
    const idx = activeTasks.value.findIndex(t => t.id === task.id);
    if (idx >= 0) {
      activeTasks.value[idx] = { ...activeTasks.value[idx], ...task };
    } else {
      activeTasks.value.unshift(task);
    }
  }

  function updateTaskStatus(id: string, updates: Partial<GenerationTask>) {
    const task = activeTasks.value.find(t => t.id === id);
    if (task) {
      Object.assign(task, updates);
    }
  }

  function removeTask(id: string) {
    activeTasks.value = activeTasks.value.filter(t => t.id !== id);
  }

  function toggleDrawer() {
    isDrawerOpen.value = !isDrawerOpen.value;
  }

  return {
    activeTasks,
    isDrawerOpen,
    runningCount,
    waitingReviewCount,
    addTask,
    updateTaskStatus,
    removeTask,
    toggleDrawer
  };
});
