<script setup lang="ts">
import DotGridBackground from './DotGridBackground.vue';
import GradientGlow from './GradientGlow.vue';

withDefaults(defineProps<{
  theme?: 'light' | 'dark';
}>(), {
  theme: 'light'
});
</script>

<template>
  <div class="ambient-bg-wrapper" :class="theme">
    <DotGridBackground :opacity="theme === 'dark' ? 0.08 : 0.045" :dotColor="theme === 'dark' ? '#818cf8' : '#4f46e5'" />
    <GradientGlow color="primary" :size="600" top="-100px" left="-100px" :opacity="theme === 'dark' ? 0.22 : 0.12" />
    <GradientGlow color="cyan" :size="500" top="20%" right="-150px" :opacity="theme === 'dark' ? 0.18 : 0.1" />
    <GradientGlow color="violet" :size="550" bottom="-150px" left="15%" :opacity="theme === 'dark' ? 0.2 : 0.08" />
  </div>
</template>

<style scoped>
.ambient-bg-wrapper {
  position: absolute;
  inset: 0;
  overflow: hidden;
  pointer-events: none;
  z-index: 0;
}

.ambient-bg-wrapper.dark {
  background: radial-gradient(circle at 50% 0%, #1e1b4b 0%, #0f172a 100%);
}

.ambient-bg-wrapper.light {
  background: radial-gradient(circle at 50% 0%, #f8fafc 0%, #f1f5f9 100%);
}
</style>
