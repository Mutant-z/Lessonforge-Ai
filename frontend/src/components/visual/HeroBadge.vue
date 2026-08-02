<script setup lang="ts">
defineProps<{
  text: string;
  badge?: string;
}>();
</script>

<template>
  <div class="hero-badge-capsule">
    <span class="badge-dot"></span>
    <span v-if="badge" class="badge-tag">{{ badge }}</span>
    <span class="badge-text">{{ text }}</span>
  </div>
</template>

<style scoped>
.hero-badge-capsule {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 5px 14px 5px 10px;
  background: var(--surface-emphasis);
  border: 1px solid var(--color-primary-border);
  border-radius: var(--radius-pill);
  box-shadow: var(--shadow-xs);
  font-size: 12px;
  font-weight: 600;
  color: var(--color-primary);
  width: fit-content;
}

.badge-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background-color: var(--color-primary);
  box-shadow: 0 0 8px var(--color-primary);
}

.badge-tag {
  background: var(--color-primary);
  color: #ffffff;
  padding: 1px 7px;
  border-radius: var(--radius-pill);
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.badge-text {
  letter-spacing: 0.02em;
}
</style>
