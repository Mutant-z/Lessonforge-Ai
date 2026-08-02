export type ContentBlockType =
  | 'text'
  | 'markdown'
  | 'heading'
  | 'table'
  | 'code'
  | 'json'
  | 'yaml'
  | 'mermaid'
  | 'math'
  | 'image'
  | 'file'
  | 'citation'
  | 'timeline'
  | 'objective_list'
  | 'slide'
  | 'exercise'
  | 'storyboard'
  | 'quality_issue'
  | 'alert'
  | 'action'
  | 'unknown';

export interface ContentBlockMetadata {
  artifact_type?: string;
  editable?: boolean;
  language?: string;
  title?: string;
  status?: 'streaming' | 'complete' | 'error';
  severity?: 'critical' | 'major' | 'minor';
  source?: string;
  page_index?: number;
  [key: string]: any;
}

export interface ContentBlock {
  block_id: string;
  type: ContentBlockType;
  content: string | any;
  status?: 'streaming' | 'complete' | 'error';
  metadata?: ContentBlockMetadata;
}
