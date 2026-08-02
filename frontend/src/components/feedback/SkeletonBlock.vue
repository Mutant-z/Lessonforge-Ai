<script setup lang="ts">
defineProps<{
  rows?: number;
  type?: 'card' | 'table' | 'text' | 'ppt';
}>();
</script>

<template>
  <div class="skeleton-container">
    <div v-if="type === 'ppt'" class="skeleton-ppt-box shimmer-effect">
      <div class="skeleton-ppt-title shimmer-effect"></div>
      <div class="skeleton-ppt-body shimmer-effect"></div>
    </div>
    <div v-else-if="type === 'card'" class="skeleton-card-grid">
      <div v-for="n in (rows || 3)" :key="n" class="skeleton-card shimmer-effect"></div>
    </div>
    <div v-else class="skeleton-text-list">
      <div v-for="n in (rows || 4)" :key="n" class="skeleton-line shimmer-effect" :style="{ width: `${n % 2 === 0 ? 80 : 95}%` }"></div>
    </div>
  </div>
</template>

<style scoped>
.skeleton-container {
  width: 100%;
  padding: 16px 0;
}

.skeleton-ppt-box {
  width: 100%;
  aspect-ratio: 16 / 9;
  border-radius: var(--radius-lg);
  padding: 32px;
  background: var(--bg-subtle);
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.skeleton-ppt-title {
  height: 28px;
  width: 45%;
  border-radius: var(--radius-sm);
  background: var(--bg-hover);
}

.skeleton-ppt-body {
  flex: 1;
  border-radius: var(--radius-sm);
  background: var(--bg-hover);
}

.skeleton-card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 16px;
}

.skeleton-card {
  height: 120px;
  border-radius: var(--radius-md);
  background: var(--bg-subtle);
}

.skeleton-text-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.skeleton-line {
  height: 16px;
  border-radius: var(--radius-xs);
  background: var(--bg-subtle);
}
</style>
