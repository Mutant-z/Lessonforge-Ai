<script setup lang="ts">
withDefaults(defineProps<{
  opacity?: number;
  dotColor?: string;
  size?: number;
}>(), {
  opacity: 0.05,
  dotColor: '#4f46e5',
  size: 24
});
</script>

<template>
  <div 
    class="dot-grid-pattern" 
    :style="{
      opacity,
      backgroundImage: `radial-gradient(${dotColor} 1.5px, transparent 1.5px)`,
      backgroundSize: `${size}px ${size}px`
    }"
  />
</template>

<style scoped>
.dot-grid-pattern {
  position: absolute;
  inset: 0;
  pointer-events: none;
  z-index: 0;
}
</style>
