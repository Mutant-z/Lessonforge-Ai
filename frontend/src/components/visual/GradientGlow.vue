<script setup lang="ts">
import { computed } from 'vue';

const props = withDefaults(defineProps<{
  color?: 'primary' | 'cyan' | 'violet' | 'mint' | 'amber';
  size?: number;
  top?: string;
  left?: string;
  right?: string;
  bottom?: string;
  opacity?: number;
  blur?: number;
}>(), {
  color: 'primary',
  size: 480,
  opacity: 0.15,
  blur: 90
});

const colorMap = {
  primary: '91, 92, 240',
  cyan: '6, 182, 212',
  violet: '139, 92, 246',
  mint: '16, 185, 129',
  amber: '245, 158, 11'
};

const styleObj = computed(() => {
  const rgb = colorMap[props.color] || colorMap.primary;
  return {
    width: `${props.size}px`,
    height: `${props.size}px`,
    top: props.top,
    left: props.left,
    right: props.right,
    bottom: props.bottom,
    background: `radial-gradient(circle, rgba(${rgb}, ${props.opacity}) 0%, rgba(${rgb}, 0) 70%)`,
    filter: `blur(${props.blur}px)`
  };
});
</script>

<template>
  <div class="gradient-glow-blob" :style="styleObj" />
</template>

<style scoped>
.gradient-glow-blob {
  position: absolute;
  border-radius: 50%;
  pointer-events: none;
  z-index: 0;
  transition: all 0.5s ease-out;
}
</style>
