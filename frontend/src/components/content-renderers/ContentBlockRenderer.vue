<script setup lang="ts">
import type { ContentBlock } from '../../types';
import MarkdownRenderer from './MarkdownRenderer.vue';
import CodeBlockRenderer from './CodeBlockRenderer.vue';
import JsonTreeRenderer from './JsonTreeRenderer.vue';
import YamlRenderer from './YamlRenderer.vue';
import MermaidRenderer from './MermaidRenderer.vue';
import MathRenderer from './MathRenderer.vue';
import FileOutputCard from './FileOutputCard.vue';
import CitationCard from './CitationCard.vue';
import UnknownBlockRenderer from './UnknownBlockRenderer.vue';

defineProps<{
  block: ContentBlock;
  isStreaming?: boolean;
}>();
</script>

<template>
  <div class="content-block-dispatcher">
    <template v-if="block.type === 'markdown' || block.type === 'text'">
      <MarkdownRenderer :content="typeof block.content === 'string' ? block.content : String(block.content)" :is-streaming="isStreaming" />
    </template>

    <template v-else-if="block.type === 'code'">
      <CodeBlockRenderer :code="typeof block.content === 'string' ? block.content : JSON.stringify(block.content, null, 2)" :language="block.metadata?.language" />
    </template>

    <template v-else-if="block.type === 'json'">
      <JsonTreeRenderer :content="block.content" />
    </template>

    <template v-else-if="block.type === 'yaml'">
      <YamlRenderer :content="typeof block.content === 'string' ? block.content : String(block.content)" />
    </template>

    <template v-else-if="block.type === 'mermaid'">
      <MermaidRenderer :content="typeof block.content === 'string' ? block.content : String(block.content)" :is-streaming="isStreaming" />
    </template>

    <template v-else-if="block.type === 'math'">
      <MathRenderer :math="typeof block.content === 'string' ? block.content : String(block.content)" />
    </template>

    <template v-else-if="block.type === 'file'">
      <FileOutputCard 
        :file-name="block.metadata?.title || '生成文件'" 
        :file-type="block.metadata?.language"
        :file-size="block.metadata?.size"
      />
    </template>

    <template v-else-if="block.type === 'citation'">
      <CitationCard 
        :source-name="block.metadata?.title || '引用来源'"
        :excerpt="typeof block.content === 'string' ? block.content : undefined"
      />
    </template>

    <template v-else>
      <UnknownBlockRenderer :block="block" />
    </template>
  </div>
</template>
