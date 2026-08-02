<script setup lang="ts">
defineProps<{
  eyebrow?: string;
  title: string;
  subtitle?: string;
}>();
</script>

<template>
  <div class="page-header animate-fade-in">
    <div>
      <div v-if="eyebrow" class="page-header-eyebrow">{{ eyebrow }}</div>
      <h1 class="page-header-title">{{ title }}</h1>
      <p v-if="subtitle" class="page-header-subtitle">{{ subtitle }}</p>
    </div>

    <div v-if="$slots.actions" class="page-header-actions">
      <slot name="actions"></slot>
    </div>
  </div>
</template>

<style scoped>
.page-header-actions {
  display: flex;
  gap: 10px;
  align-items: center;
}
</style>
