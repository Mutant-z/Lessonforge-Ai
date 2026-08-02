import type { ContentBlock } from '../types';

export function parseContentToBlocks(rawText: string): ContentBlock[] {
  if (!rawText || !rawText.trim()) return [];

  const blocks: ContentBlock[] = [];
  // Regex to detect code fences ```lang ... ```
  const codeBlockRegex = /```([a-zA-Z0-9_\-+]*)\n([\s\S]*?)(?:```|$)/g;

  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = codeBlockRegex.exec(rawText)) !== null) {
    const textBefore = rawText.slice(lastIndex, match.index);
    if (textBefore.trim()) {
      blocks.push(...parseMarkdownSegments(textBefore));
    }

    const lang = (match[1] || 'text').toLowerCase();
    const codeContent = match[2];
    const isUnclosed = !match[0].endsWith('```');

    if (lang === 'mermaid') {
      blocks.push({
        block_id: `mermaid-${match.index}`,
        type: 'mermaid',
        content: codeContent,
        status: isUnclosed ? 'streaming' : 'complete'
      });
    } else if (lang === 'json') {
      blocks.push({
        block_id: `json-${match.index}`,
        type: 'json',
        content: codeContent,
        status: isUnclosed ? 'streaming' : 'complete'
      });
    } else if (lang === 'yaml' || lang === 'yml') {
      blocks.push({
        block_id: `yaml-${match.index}`,
        type: 'yaml',
        content: codeContent,
        status: isUnclosed ? 'streaming' : 'complete'
      });
    } else {
      blocks.push({
        block_id: `code-${match.index}`,
        type: 'code',
        content: codeContent,
        status: isUnclosed ? 'streaming' : 'complete',
        metadata: { language: lang }
      });
    }

    lastIndex = match.index + match[0].length;
  }

  const remainingText = rawText.slice(lastIndex);
  if (remainingText.trim()) {
    blocks.push(...parseMarkdownSegments(remainingText));
  }

  return blocks;
}

function parseMarkdownSegments(text: string): ContentBlock[] {
  const blocks: ContentBlock[] = [];
  // Separate out inline or block math if needed, or leave as markdown block
  blocks.push({
    block_id: `md-${Math.random().toString(36).substring(2, 9)}`,
    type: 'markdown',
    content: text,
    status: 'complete'
  });
  return blocks;
}
