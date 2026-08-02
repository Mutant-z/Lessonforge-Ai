<script setup lang="ts">
import CodeBlockRenderer from './CodeBlockRenderer.vue';

defineProps<{
  content: string;
}>();
</script>

<template>
  <div class="yaml-renderer">
    <CodeBlockRenderer :code="content" language="yaml" />
  </div>
</template>
