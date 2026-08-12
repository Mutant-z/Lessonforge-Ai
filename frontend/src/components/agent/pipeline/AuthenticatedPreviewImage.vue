<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue';
import { api } from '../../../api/client';
import { authenticatedPreviewRequestUrl } from './candidatePreview';

const props = defineProps<{
  src: string;
  alt: string;
}>();

const resolvedSrc = ref('');
const state = ref<'idle' | 'loading' | 'ready' | 'failed'>('idle');
let ownedObjectUrl = '';
let loadEpoch = 0;

function releaseObjectUrl() {
  if (ownedObjectUrl) URL.revokeObjectURL(ownedObjectUrl);
  ownedObjectUrl = '';
  resolvedSrc.value = '';
}

async function loadPreview() {
  const epoch = ++loadEpoch;
  releaseObjectUrl();
  const source = props.src.trim();
  if (!source) {
    state.value = 'idle';
    return;
  }
  if (/^(?:data:image\/|blob:|\/static\/|\/uploads\/)/.test(source)) {
    resolvedSrc.value = source;
    state.value = 'ready';
    return;
  }
  state.value = 'loading';
  try {
    const response = await api.get(authenticatedPreviewRequestUrl(source), {
      responseType: 'blob',
    });
    const objectUrl = URL.createObjectURL(response.data);
    if (epoch !== loadEpoch) {
      URL.revokeObjectURL(objectUrl);
      return;
    }
    ownedObjectUrl = objectUrl;
    resolvedSrc.value = objectUrl;
    state.value = 'ready';
  } catch {
    if (epoch === loadEpoch) state.value = 'failed';
  }
}

function markFailed() {
  state.value = 'failed';
  releaseObjectUrl();
}

watch(() => props.src, loadPreview, { immediate: true });

onBeforeUnmount(() => {
  loadEpoch += 1;
  releaseObjectUrl();
});
</script>

<template>
  <img
    v-if="state === 'ready' && resolvedSrc"
    :src="resolvedSrc"
    :alt="alt"
    @error="markFailed"
  >
  <div v-else class="authenticated-preview-state" :class="state">
    <span>{{ state === 'failed' ? '预览加载失败' : '预览加载中…' }}</span>
    <button v-if="state === 'failed'" type="button" @click="loadPreview">重试</button>
  </div>
</template>

<style scoped>
img,
.authenticated-preview-state {
  width: 100%;
  height: 100%;
}

img {
  display: block;
  object-fit: contain;
}

.authenticated-preview-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  color: #64748b;
  font-size: 10px;
  font-weight: 750;
  background:
    linear-gradient(135deg, rgba(99, 102, 241, 0.07) 25%, transparent 25%) 0 0 / 12px 12px,
    #f8fafc;
}

.authenticated-preview-state.failed { color: #b91c1c; }

button {
  border: 1px solid #c4b5fd;
  border-radius: 6px;
  padding: 3px 8px;
  background: #ffffff;
  color: #5b21b6;
  font: inherit;
  cursor: pointer;
}
</style>
