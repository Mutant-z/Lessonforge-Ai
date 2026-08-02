<script setup lang="ts">
defineProps<{
  active?: boolean;
}>();
</script>

<template>
  <span v-if="active !== false" class="streaming-cursor-dot" title="内容生成中..."></span>
</template>
