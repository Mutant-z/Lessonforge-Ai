import { defineStore } from 'pinia';
import { api, errorMessage } from '../api/client';
import { pipelineApi } from '../api/pipeline';
import type { VideoScriptMode } from '../api/pipeline';
import type { Artifact, ArtifactUpdateSource, ChatAttachment, CourseProjectWorkspace, CourseTask, HydrationStatus, PPTPolishModality, ProjectAgentMessage, ProjectTaskEvent, SlideRepairNotes } from '../types';
import { useCourseStore } from './courses';
import { isNativeVideoResolution } from '../utils/videoResolution';

const TASK_EVENTS = [
  'project_planning_updated',
  'task_status_changed',
  'task_progress_updated',
  'task_activity_updated',
  'agent_message_created',
  'agent_message_started',
  'agent_message_delta',
  'agent_message_completed',
  'agent_message_failed',
  'artifact_version_created',
  'task_dependency_stale',
  'task_failed',
  'video_generation_started',
  'video_scene_started',
  'video_scene_progress',
  'video_scene_completed',
  'video_scene_failed',
  'video_composition_started',
  'video_composition_completed',
  'video_generation_completed',
  'video_generation_failed',
  'quality_updated',
  'agent_initialization_started',
  'agent_initialization_progress',
  'agent_initialization_completed',
  'agent_initialization_failed',
  // 多 Agent 流水线（PPT）事件
  'agent_started',
  'agent_completed',
  'pipeline_started',
  'agent_status_delta',
  'agent_status_completed',
  'tool_call_started',
  'tool_call_delta',
  'tool_call_completed',
  'artifact_created',
  'artifact_started',
  'artifact_patch',
  'asset_generated',
  'qa_completed',
  'qa_issue_found',
  'revision_started',
  'revision_completed',
  'task_paused',
  'task_resumed',
  'pipeline_completed',
  'pipeline_failed',
  'agent_thought_chunk',
  'run.started', 'run.completed', 'run.failed', 'run.paused', 'run.resumed',
  'plan.created', 'agent.started', 'agent.progress', 'agent.completed', 'agent.handoff',
  'skill.discovered', 'skill.loaded', 'skill.completed', 'skill.failed',
  'tool.started', 'tool.progress', 'tool.completed', 'tool.failed',
  'artifact.created', 'artifact.updated', 'slide.planned', 'slide.started',
  'slide.content.updated', 'slide.layout.updated', 'slide.asset.updated', 'slide.rendering',
  'slide.rendered', 'slide.qa', 'slide.completed', 'slide.failed',
  'qa.started', 'qa.issue', 'qa.completed', 'validation.completed', 'validation.issue', 'repair.started', 'repair.completed',
  'draft.update.started', 'draft.update.completed',
  'layout.compile.result', 'polish.result',
  'human.required', 'run.instruction.queued', 'run.instruction.merged',
  'intent.recognized', 'intent.resolved', 'edit.plan.created', 'slide.change.applied',
  'edit.corrected', 'qa.warning', 'agent.clarification.required', 'artifact.diff',
  // 共享项目记忆事件
  'project_memory.updated', 'context.snapshot_created', 'artifact.published', 'memory.source_read',
  // 视频生成偏好设置
  'video_generation.setting.updated',
  'course.metadata.updated',
];

/** 流水线事件被路由到项目 store 的收件箱，工作台据此渲染时间线 */
const PIPELINE_EVENT_TYPES = new Set([
  'pipeline_started', 'agent_started', 'agent_completed', 'agent_status_delta', 'agent_status_completed',
  'tool_call_started', 'tool_call_delta', 'tool_call_completed',
  'artifact_started', 'artifact_patch', 'artifact_created', 'asset_generated', 'qa_issue_found', 'qa_completed', 'revision_started',
  'revision_completed', 'task_paused', 'task_resumed', 'pipeline_completed', 'pipeline_failed',
  'agent_thought_chunk',
  'run.started', 'run.completed', 'run.failed', 'run.paused', 'run.resumed',
  'plan.created', 'agent.started', 'agent.progress', 'agent.completed', 'agent.handoff',
  'skill.discovered', 'skill.loaded', 'skill.completed', 'skill.failed',
  'tool.started', 'tool.progress', 'tool.completed', 'tool.failed',
  'artifact.created', 'artifact.updated', 'slide.planned', 'slide.started',
  'slide.content.updated', 'slide.layout.updated', 'slide.asset.updated', 'slide.rendering',
  'slide.rendered', 'slide.qa', 'slide.completed', 'slide.failed', 'qa.started', 'qa.issue', 'validation.completed', 'validation.issue',
  'draft.update.started', 'draft.update.completed',
  'repair.started', 'repair.completed', 'human.required', 'run.instruction.queued', 'run.instruction.merged',
  'layout.compile.result', 'polish.result',
  'intent.recognized', 'intent.resolved', 'edit.plan.created', 'slide.change.applied',
  'edit.corrected', 'qa.warning', 'agent.clarification.required', 'artifact.diff',
]);

function deduplicateMessages(messages: ProjectAgentMessage[]): ProjectAgentMessage[] {
  const seenIds = new Set<string>();
  const result: ProjectAgentMessage[] = [];
  for (const m of messages) {
    if (!m.id || seenIds.has(m.id)) continue;
    seenIds.add(m.id);
    result.push(m);
  }
  return result;
}

function attachmentIds(attachments: ChatAttachment[]): string[] {
  return attachments.map((attachment) => attachment.id);
}

function reconcileArtifact(
  incoming: Artifact | null,
  existing: Artifact | null | undefined,
  source: ArtifactUpdateSource,
): { artifact: Artifact | null; conflict: boolean } {
  if (!incoming) return { artifact: existing || null, conflict: false };
  if (!existing) return { artifact: incoming, conflict: false };
  if (incoming.course_id !== existing.course_id || incoming.artifact_type !== existing.artifact_type) {
    return { artifact: existing, conflict: true };
  }
  if (incoming.version < existing.version) {
    if (import.meta.env.DEV) console.info('[artifact-version] rejected stale artifact', {
      source, incoming_id: incoming.id, incoming_version: incoming.version,
      official_id: existing.id, official_version: existing.version,
    });
    return { artifact: existing, conflict: false };
  }
  if (incoming.version === existing.version && incoming.id !== existing.id) {
    console.warn('[artifact-version] same version has different ids', {
      source, incoming_id: incoming.id, incoming_version: incoming.version,
      official_id: existing.id, official_version: existing.version,
    });
    return { artifact: existing, conflict: true };
  }
  if (incoming.id === existing.id) {
    Object.assign(existing, incoming);
    return { artifact: existing, conflict: false };
  }
  return { artifact: incoming, conflict: false };
}

function reconcileTaskArtifact(
  incoming: CourseTask,
  existing: CourseTask | null | undefined,
  source: ArtifactUpdateSource,
  latestResolutionEventId = 0,
): {
  task: CourseTask;
  conflict: boolean;
} {
  let guardedIncoming = incoming;
  if (
    existing?.id === incoming.id
    && ['video_script', 'video_generation'].includes(incoming.task_type)
    && Number(incoming.event_cursor || 0) < latestResolutionEventId
    && isNativeVideoResolution(existing.preferred_video_resolution)
  ) {
    guardedIncoming = {
      ...incoming,
      preferred_video_resolution: existing.preferred_video_resolution,
    };
  }
  const existingArtifact = existing?.id === guardedIncoming.id ? existing.current_artifact : null;
  const result = reconcileArtifact(guardedIncoming.current_artifact, existingArtifact, source);
  return {
    task: result.artifact === guardedIncoming.current_artifact
      ? guardedIncoming
      : { ...guardedIncoming, current_artifact: result.artifact },
    conflict: result.conflict,
  };
}

/** QA / 修复事件里可能携带的问题对象（兼容 legacy 与 canonical 两种信封） */
interface RepairIssueShape {
  slide_id?: unknown;
  severity?: unknown;
  rule_id?: unknown;
  message?: unknown;
}

const REPAIR_SEVERITY_LABELS: Record<string, string> = { critical: '严重', major: '主要', minor: '次要' };

function collectRepairIssues(event: Record<string, any>): RepairIssueShape[] {
  const payload = event.payload && typeof event.payload === 'object' ? event.payload : {};
  const candidates: unknown[] = [];
  if (Array.isArray(payload.issues)) candidates.push(...payload.issues);
  if (payload.issue && typeof payload.issue === 'object') candidates.push(payload.issue);
  if (event.issue && typeof event.issue === 'object') candidates.push(event.issue);
  if (Array.isArray(event.issues)) candidates.push(...event.issues);
  return candidates.filter((item): item is RepairIssueShape => Boolean(item) && typeof item === 'object');
}

function formatRepairNote(issue: RepairIssueShape): string {
  const severity = REPAIR_SEVERITY_LABELS[String(issue.severity || '')] || '';
  const message = String(issue.message || '').trim();
  const rule = issue.rule_id ? `（${String(issue.rule_id)}）` : '';
  return `${severity ? `${severity}：` : ''}${message || '页面存在质量问题'}${rule}`;
}

export const useProjectStore = defineStore('project', {
  state: () => ({
    project: null as CourseProjectWorkspace | null,
    currentTask: null as CourseTask | null,
    loading: false,
    connectionError: '',
    lastEventId: 0,
    videoResolutionEventId: 0,
    connectedCourseId: null as string | null,
    connectingCourseId: null as string | null,
    eventSource: null as EventSource | null,
    reconnectTimer: null as number | null,
    reconnectAttempt: 0,
    activeTaskPollTimer: null as number | null,
    activeTaskPollInFlight: false,
    pipelineEvents: [] as Array<{ type: string; data: Record<string, any>; event_id: number }>,
    pipelineStatus: '' as string,
    slideRepairNotes: {} as SlideRepairNotes,
    officialArtifact: null as Artifact | null,
    viewedArtifact: null as Artifact | null,
    hydrationStatus: 'idle' as HydrationStatus,
    projectRequestEpoch: 0,
    taskRequestEpoch: 0,
    artifactConflict: null as Record<string, unknown> | null,
  }),
  getters: {
    tasks: state => state.project?.tasks || [],
    completion(state) {
      const tasks = (state.project?.tasks || []).filter(task => task.task_type !== 'video_generation');
      return tasks.length ? Math.round(tasks.reduce((sum, task) => sum + task.progress, 0) / tasks.length) : 0;
    },
  },
  actions: {
    setHydrationStatus(status: HydrationStatus) {
      this.hydrationStatus = status;
    },
    viewArtifact(artifact: Artifact | null) {
      this.viewedArtifact = artifact;
    },
    acceptCurrentArtifact(artifact: Artifact, source: ArtifactUpdateSource = 'refresh') {
      if (!this.currentTask
        || artifact.course_id !== this.currentTask.course_id
        || artifact.artifact_type !== this.currentTask.task_type) return false;
      const result = reconcileArtifact(artifact, this.currentTask.current_artifact, source);
      if (result.conflict) {
        this.artifactConflict = {
          source, incoming_artifact_id: artifact.id, incoming_version: artifact.version,
          official_artifact_id: this.currentTask.current_artifact?.id,
          official_version: this.currentTask.current_artifact?.version,
        };
        return false;
      }
      this.currentTask.current_artifact = result.artifact;
      this.syncOfficialArtifact();
      this.replaceTask(this.currentTask);
      return true;
    },
    syncOfficialArtifact() {
      const previousId = this.officialArtifact?.id;
      this.officialArtifact = this.currentTask?.current_artifact || null;
      if (previousId && this.officialArtifact?.id !== previousId) this.viewedArtifact = null;
      if (this.viewedArtifact?.course_id !== this.officialArtifact?.course_id
        || this.viewedArtifact?.artifact_type !== this.officialArtifact?.artifact_type) {
        this.viewedArtifact = null;
      }
    },
    async open(courseId: string) {
      const epoch = ++this.projectRequestEpoch;
      this.loading = true;
      this.hydrationStatus = 'loading_project';
      try {
        const { data } = await api.get<CourseProjectWorkspace>(`/courses/${courseId}/project`);
        if (epoch !== this.projectRequestEpoch) return data;
        const previousTasks = this.project?.course.id === courseId ? this.project.tasks : [];
        const resolutionGuard = this.project?.course.id === courseId ? this.videoResolutionEventId : 0;
        data.tasks = data.tasks.map(task => reconcileTaskArtifact(
          task,
          previousTasks.find(item => item.id === task.id),
          'project_snapshot',
          resolutionGuard,
        ).task);
        const courseChanged = Boolean(this.project && this.project.course.id !== courseId);
        this.project = data;
        this.lastEventId = courseChanged
          ? Number(data.event_cursor || 0)
          : Math.max(this.lastEventId, Number(data.event_cursor || 0));
        if (courseChanged) {
          this.pipelineEvents = [];
          this.pipelineStatus = '';
          this.videoResolutionEventId = 0;
          this.slideRepairNotes = {};
          this.officialArtifact = null;
          this.viewedArtifact = null;
        }
        const courses = useCourseStore();
        courses.current = data.course as any;
        const existing = courses.items.findIndex(item => item.id === data.course.id);
        if (existing >= 0) courses.items[existing] = { ...courses.items[existing], ...data.course } as any;
        else courses.items.unshift(data.course as any);
        this.connect(courseId);
        if (data.agent_initialization?.status === 'not_initialized' && data.planning.status === 'ready') {
          try {
            await this.initializeAgents(courseId);
          } catch (cause) {
            data.agent_initialization.status = 'failed';
            data.agent_initialization.error = { code: 'agent_initialization_start_failed', message: errorMessage(cause), retryable: true };
          }
        }
        return data;
      } finally {
        this.loading = false;
      }
    },
    async openTask(courseId: string, taskType: string) {
      const epoch = ++this.taskRequestEpoch;
      this.hydrationStatus = 'loading_task_snapshot';
      this.viewedArtifact = null;
      this.pipelineStatus = '';
      if (!this.project || this.project.course.id !== courseId) {
        await this.open(courseId);
      } else {
        this.connect(courseId);
      }
      const { data } = await api.get<CourseTask>(`/courses/${courseId}/tasks/${taskType}`);
      if (epoch !== this.taskRequestEpoch) return data;
      const result = reconcileTaskArtifact(
        data,
        this.currentTask || this.project?.tasks.find(item => item.id === data.id),
        'task_snapshot',
        this.videoResolutionEventId,
      );
      const hydrated = result.task;
      if (result.conflict) {
        this.artifactConflict = { source: 'task_snapshot', task_id: data.id, incoming_artifact_id: data.current_artifact?.id };
      }
      if (this.currentTask?.id === hydrated.id) Object.assign(this.currentTask, hydrated);
      else this.currentTask = hydrated;
      this.lastEventId = Math.max(this.lastEventId, Number(data.event_cursor || 0));
      this.syncOfficialArtifact();
      this.replaceTask(hydrated);
      if (['queued', 'running'].includes(hydrated.status)) this.startActiveTaskPolling(courseId, taskType);
      else this.stopActiveTaskPolling();
      return hydrated;
    },
    replaceTask(task: CourseTask) {
      if (!this.project) return;
      const index = this.project.tasks.findIndex(item => item.id === task.id);
      if (index >= 0) {
        const result = reconcileTaskArtifact(
          task, this.project.tasks[index], 'refresh', this.videoResolutionEventId,
        );
        this.project.tasks[index] = { ...this.project.tasks[index], ...result.task };
      }
    },
    async sendMessage(courseId: string, taskType: string, content: string, attachments: ChatAttachment[] = []) {
      const local: ProjectAgentMessage = {
        id: `local-${crypto.randomUUID()}`,
        role: 'user',
        content,
        status: 'pending',
        metadata: attachments.length ? { attachments } : undefined,
        created_at: new Date().toISOString(),
      };
      if (this.currentTask) this.currentTask.messages = [...(this.currentTask.messages || []), local];
      try {
        const { data } = await api.post(`/courses/${courseId}/tasks/${taskType}/messages`, {
          content,
          ...(attachments.length ? { attachment_ids: attachmentIds(attachments) } : {}),
        });
        Object.assign(local, { id: data.message_id, run_id: data.run_id });
        if (this.currentTask) {
          this.currentTask.status = 'queued';
          this.currentTask.active_run_id = data.run_id;
          this.replaceTask(this.currentTask);
        }
        this.startActiveTaskPolling(courseId, taskType);
        return data;
      } catch (cause) {
        local.status = 'failed';
        throw cause;
      }
    },
    async enqueuePPTInstruction(
      runId: string,
      content: string,
      selectedSlideIds: string[] = [],
      resumeIfPaused = false,
      modality: PPTPolishModality = 'auto',
      activeSlideId?: string,
      attachments: ChatAttachment[] = [],
    ) {
      const local: ProjectAgentMessage = {
        id: `local-${crypto.randomUUID()}`,
        role: 'user',
        content,
        status: 'pending',
        run_id: runId,
        metadata: attachments.length ? { attachments } : undefined,
        created_at: new Date().toISOString(),
      };
      if (this.currentTask) this.currentTask.messages = [...(this.currentTask.messages || []), local];
      try {
        const data = await pipelineApi.enqueue(runId, content, selectedSlideIds, resumeIfPaused, modality, activeSlideId, {}, attachmentIds(attachments));
        Object.assign(local, data.message, { status: 'completed' as const });
        if (this.currentTask) {
          this.currentTask.messages = deduplicateMessages([...(this.currentTask.messages || [])]);
          if (data.status === 'resumed') this.currentTask.status = 'queued';
        }
        if (data.status === 'resumed') this.pipelineStatus = 'queued';
        return data;
      } catch (cause) {
        local.status = 'failed';
        if (this.currentTask) this.currentTask.messages = [...(this.currentTask.messages || [])];
        throw cause;
      }
    },
    async createPPTRun(
      courseId: string,
      content: string,
      selectedSlideIds: string[] = [],
      modality: PPTPolishModality = 'auto',
      activeSlideId?: string,
      attachments: ChatAttachment[] = [],
    ) {
      const previousPipelineStatus = this.pipelineStatus;
      const previousTaskStatus = this.currentTask?.status;
      const previousPipelineEvents = this.pipelineEvents;
      const previousRepairNotes = this.slideRepairNotes;
      const local: ProjectAgentMessage = {
        id: `local-${crypto.randomUUID()}`,
        role: 'user',
        content,
        status: 'pending',
        metadata: attachments.length ? { attachments } : undefined,
        created_at: new Date().toISOString(),
      };
      if (this.currentTask) this.currentTask.messages = [...(this.currentTask.messages || []), local];
      // Clear the previous run before starting the request. Clearing after the
      // response races with SSE and can erase the new run's first visible status
      // events (pipeline_started / orchestrator status), making Send look inert.
      this.pipelineEvents = [];
      this.slideRepairNotes = {};
      this.pipelineStatus = 'queued';
      if (this.currentTask) this.currentTask.status = 'queued';
      try {
        const data = await pipelineApi.createRun(courseId, content, selectedSlideIds, modality, activeSlideId, {}, attachmentIds(attachments));
        Object.assign(local, { id: data.message_id, run_id: data.run_id, status: 'completed' as const });
        this.pipelineStatus = 'queued';
        if (this.currentTask) {
          this.currentTask.status = 'queued';
          this.currentTask.active_run_id = data.run_id;
          this.currentTask.error = null;
          this.replaceTask(this.currentTask);
        }
        this.startActiveTaskPolling(courseId, 'ppt');
        return data;
      } catch (cause) {
        local.status = 'failed';
        this.pipelineEvents = previousPipelineEvents;
        this.slideRepairNotes = previousRepairNotes;
        this.pipelineStatus = previousPipelineStatus;
        if (this.currentTask && previousTaskStatus) this.currentTask.status = previousTaskStatus;
        throw cause;
      }
    },
    async runTask(
      courseId: string,
      taskType: string,
      action: 'initial' | 'retry' | 'sync_dependencies' | 'sync_context' | 'recompose',
      options: Record<string, unknown> = {},
    ) {
      const { data } = await api.post(`/courses/${courseId}/tasks/${taskType}/runs`, { action, ...options });
      await this.openTask(courseId, taskType);
      this.startActiveTaskPolling(courseId, taskType);
      return data;
    },
    /** 教学设计 V2：创建带章节作用域的 message 运行（流式执行时间线）。 */
    async createLessonPlanRun(
      courseId: string,
      content: string,
      selectedSectionIds: string[] = [],
      mode: 'auto' | 'content' | 'structure' | 'timing' | 'qa' = 'auto',
      activeSectionId?: string,
      attachments: ChatAttachment[] = [],
    ) {
      const previousPipelineStatus = this.pipelineStatus;
      const previousPipelineEvents = this.pipelineEvents;
      const local: ProjectAgentMessage = {
        id: `local-${crypto.randomUUID()}`,
        role: 'user',
        content,
        status: 'pending',
        metadata: attachments.length ? { attachments } : undefined,
        created_at: new Date().toISOString(),
      };
      if (this.currentTask) this.currentTask.messages = [...(this.currentTask.messages || []), local];
      this.pipelineEvents = [];
      this.pipelineStatus = 'queued';
      if (this.currentTask) this.currentTask.status = 'queued';
      try {
        const data = await pipelineApi.createLessonPlanRun(courseId, content, selectedSectionIds, mode, activeSectionId, attachmentIds(attachments));
        Object.assign(local, { id: data.message_id, run_id: data.run_id, status: 'completed' as const });
        this.pipelineStatus = 'queued';
        if (this.currentTask) {
          this.currentTask.status = 'queued';
          this.currentTask.active_run_id = data.run_id;
          this.currentTask.error = null;
          this.replaceTask(this.currentTask);
        }
        this.startActiveTaskPolling(courseId, 'lesson_plan');
        return data;
      } catch (cause) {
        local.status = 'failed';
        this.pipelineEvents = previousPipelineEvents;
        this.pipelineStatus = previousPipelineStatus;
        throw cause;
      }
    },
    /** 学习任务单 V3：创建带章节作用域的 message 运行（流式执行时间线）。 */
    async createTaskSheetRun(
      courseId: string,
      content: string,
      selectedSectionIds: string[] = [],
      mode: 'auto' | 'content' | 'structure' | 'timing' | 'qa' = 'auto',
      attachments: ChatAttachment[] = [],
    ) {
      const previousPipelineStatus = this.pipelineStatus;
      const previousPipelineEvents = this.pipelineEvents;
      const local: ProjectAgentMessage = {
        id: `local-${crypto.randomUUID()}`,
        role: 'user',
        content,
        status: 'pending',
        metadata: attachments.length ? { attachments } : undefined,
        created_at: new Date().toISOString(),
      };
      if (this.currentTask) this.currentTask.messages = [...(this.currentTask.messages || []), local];
      this.pipelineEvents = [];
      this.pipelineStatus = 'queued';
      if (this.currentTask) this.currentTask.status = 'queued';
      try {
        const data = await pipelineApi.createTaskSheetRun(courseId, content, selectedSectionIds, mode, undefined, attachmentIds(attachments));
        Object.assign(local, { id: data.message_id, run_id: data.run_id, status: 'completed' as const });
        this.pipelineStatus = 'queued';
        if (this.currentTask) {
          this.currentTask.status = 'queued';
          this.currentTask.active_run_id = data.run_id;
          this.currentTask.error = null;
          this.replaceTask(this.currentTask);
        }
        this.startActiveTaskPolling(courseId, 'task_sheet');
        return data;
      } catch (cause) {
        local.status = 'failed';
        this.pipelineEvents = previousPipelineEvents;
        this.pipelineStatus = previousPipelineStatus;
        throw cause;
      }
    },
    /** 课后练习 V2：创建带分区作用域的 message 运行（流式执行时间线）。 */
    async createExerciseRun(
      courseId: string,
      content: string,
      selectedSectionIds: string[] = [],
      mode: 'auto' | 'content' | 'structure' | 'timing' | 'qa' = 'auto',
      attachments: ChatAttachment[] = [],
    ) {
      const previousPipelineStatus = this.pipelineStatus;
      const previousPipelineEvents = this.pipelineEvents;
      const local: ProjectAgentMessage = {
        id: `local-${crypto.randomUUID()}`,
        role: 'user',
        content,
        status: 'pending',
        metadata: attachments.length ? { attachments } : undefined,
        created_at: new Date().toISOString(),
      };
      if (this.currentTask) this.currentTask.messages = [...(this.currentTask.messages || []), local];
      this.pipelineEvents = [];
      this.pipelineStatus = 'queued';
      if (this.currentTask) this.currentTask.status = 'queued';
      try {
        const data = await pipelineApi.createExerciseRun(courseId, content, selectedSectionIds, mode, undefined, attachmentIds(attachments));
        Object.assign(local, { id: data.message_id, run_id: data.run_id, status: 'completed' as const });
        this.pipelineStatus = 'queued';
        if (this.currentTask) {
          this.currentTask.status = 'queued';
          this.currentTask.active_run_id = data.run_id;
          this.currentTask.error = null;
          this.replaceTask(this.currentTask);
        }
        this.startActiveTaskPolling(courseId, 'exercise');
        return data;
      } catch (cause) {
        local.status = 'failed';
        this.pipelineEvents = previousPipelineEvents;
        this.pipelineStatus = previousPipelineStatus;
        throw cause;
      }
    },
    /** 教师逐字稿 V2：创建带章节作用域的 message 运行（流式执行时间线）。 */
    async createVerbatimRun(
      courseId: string,
      content: string,
      selectedSectionIds: string[] = [],
      mode: 'auto' | 'content' | 'structure' | 'timing' | 'qa' = 'auto',
      attachments: ChatAttachment[] = [],
    ) {
      const previousPipelineStatus = this.pipelineStatus;
      const previousPipelineEvents = this.pipelineEvents;
      const local: ProjectAgentMessage = {
        id: `local-${crypto.randomUUID()}`,
        role: 'user',
        content,
        status: 'pending',
        metadata: attachments.length ? { attachments } : undefined,
        created_at: new Date().toISOString(),
      };
      if (this.currentTask) this.currentTask.messages = [...(this.currentTask.messages || []), local];
      this.pipelineEvents = [];
      this.pipelineStatus = 'queued';
      if (this.currentTask) this.currentTask.status = 'queued';
      try {
        const data = await pipelineApi.createVerbatimRun(courseId, content, selectedSectionIds, mode, undefined, attachmentIds(attachments));
        Object.assign(local, { id: data.message_id, run_id: data.run_id, status: 'completed' as const });
        this.pipelineStatus = 'queued';
        if (this.currentTask) {
          this.currentTask.status = 'queued';
          this.currentTask.active_run_id = data.run_id;
          this.currentTask.error = null;
          this.replaceTask(this.currentTask);
        }
        this.startActiveTaskPolling(courseId, 'verbatim');
        return data;
      } catch (cause) {
        local.status = 'failed';
        this.pipelineEvents = previousPipelineEvents;
        this.pipelineStatus = previousPipelineStatus;
        throw cause;
      }
    },
    /** 视频脚本 V4：创建带章节/分镜作用域的 message 运行（流式执行时间线）。 */
    async createVideoScriptRun(
      courseId: string,
      content: string,
      selectedSectionIds: string[] = [],
      selectedSceneIds: string[] = [],
      mode: VideoScriptMode = 'auto',
      attachments: ChatAttachment[] = [],
    ) {
      const previousPipelineStatus = this.pipelineStatus;
      const previousPipelineEvents = this.pipelineEvents;
      const local: ProjectAgentMessage = {
        id: `local-${crypto.randomUUID()}`,
        role: 'user',
        content,
        status: 'pending',
        metadata: attachments.length ? { attachments } : undefined,
        created_at: new Date().toISOString(),
      };
      if (this.currentTask) this.currentTask.messages = [...(this.currentTask.messages || []), local];
      this.pipelineEvents = [];
      this.pipelineStatus = 'queued';
      if (this.currentTask) this.currentTask.status = 'queued';
      try {
        const data = await pipelineApi.createVideoScriptRun(courseId, content, selectedSectionIds, selectedSceneIds, mode, undefined, attachmentIds(attachments));
        Object.assign(local, { id: data.message_id, run_id: data.run_id, status: 'completed' as const });
        this.pipelineStatus = 'queued';
        if (this.currentTask) {
          this.currentTask.status = 'queued';
          this.currentTask.active_run_id = data.run_id;
          this.currentTask.error = null;
          this.replaceTask(this.currentTask);
        }
        this.startActiveTaskPolling(courseId, 'video_script');
        return data;
      } catch (cause) {
        local.status = 'failed';
        this.pipelineEvents = previousPipelineEvents;
        this.pipelineStatus = previousPipelineStatus;
        throw cause;
      }
    },
    async cancelTask(courseId: string, taskType: string) {
      const { data } = await api.post<{ task_id: string; status: CourseTask['status'] }>(
        `/courses/${courseId}/tasks/${taskType}/cancel`,
      );
      if (this.currentTask?.id === data.task_id) {
        this.currentTask.status = data.status;
        this.currentTask.active_run_id = null;
        this.currentTask.error = null;
        this.replaceTask(this.currentTask);
      }
      this.stopActiveTaskPolling();
      // Pull the durable terminal snapshot so a late progress event cannot keep
      // controls disabled after cancellation.
      await this.refreshCurrentTask();
      return data;
    },
    async initializeAgents(courseId: string) {
      const { data } = await api.post(`/courses/${courseId}/agent-initialization/runs`);
      if (this.project) {
        this.project.agent_initialization.status = data.status === 'completed' ? 'ready' : 'queued';
        this.project.agent_initialization.error = null;
      }
      return data;
    },
    async retryPlanning(courseId: string) {
      const { data } = await api.post(`/courses/${courseId}/project/planning/retry`);
      if (this.project) {
        this.project.planning.status = 'planning';
        this.project.planning.progress = 0;
        this.project.planning.error = null;
      }
      return data;
    },
    async approveTask(courseId: string, taskType: string) {
      const { data } = await api.post<CourseTask>(`/courses/${courseId}/tasks/${taskType}/approve`);
      const result = reconcileTaskArtifact(
        data, this.currentTask, 'approve', this.videoResolutionEventId,
      );
      this.currentTask = { ...(this.currentTask || result.task), ...result.task };
      this.syncOfficialArtifact();
      this.replaceTask(result.task);
      return data;
    },
    async setTaskModel(courseId: string, taskType: string, modelConfigId: string) {
      const { data } = await api.patch(`/courses/${courseId}/tasks/${taskType}/model`, { model_config_id: modelConfigId });
      if (this.currentTask) this.currentTask.model_config_id = data.model_config_id;
      return data;
    },
    async setTaskVisionModel(courseId: string, taskType: string, modelConfigId: string) {
      const { data } = await api.patch(`/courses/${courseId}/tasks/${taskType}/model`, { vision_model_config_id: modelConfigId });
      if (this.currentTask) this.currentTask.vision_model_config_id = data.vision_model_config_id;
      return data;
    },
    async loadMemory(courseId: string) {
      const { data } = await api.get(`/courses/${courseId}/memory`);
      if (this.project && this.project.course.id === courseId) this.project.memory = data;
      return data;
    },
    async searchMemory(courseId: string, query: string) {
      const { data } = await api.get(`/courses/${courseId}/memory/search`, { params: { q: query } });
      return data;
    },
    async setTaskImageModel(courseId: string, taskType: string, modelConfigId: string) {
      const { data } = await api.patch(`/courses/${courseId}/tasks/${taskType}/model`, { image_model_config_id: modelConfigId });
      if (this.currentTask) this.currentTask.image_model_config_id = data.image_model_config_id;
      return data;
    },
    applyEvent(type: string, event: ProjectTaskEvent) {
      if (event.event_id && event.event_id <= this.lastEventId) return;
      this.lastEventId = Math.max(this.lastEventId, event.event_id || 0);
      if (PIPELINE_EVENT_TYPES.has(type)) {
        this.pipelineEvents.push({ type, data: event as Record<string, any>, event_id: event.event_id || 0 });
        // 修复原因：qa.issue / repair.started 携带每页 QA 问题，按 slide_id 展示。
        // repair.started 表示新一轮修复开始：先清上一轮页级徽标，只保留当前轮，
        // 避免多轮累计把徽标数越滚越大。
        if (type === 'qa_issue_found' || type === 'qa.issue' || type === 'repair.started') {
          const issues = collectRepairIssues(event as unknown as Record<string, any>);
          if (issues.length) {
            const next = type === 'repair.started' ? {} : { ...this.slideRepairNotes };
            for (const issue of issues) {
              const slideId = String(issue.slide_id || '');
              if (!slideId) continue;
              const note = formatRepairNote(issue);
              const existing = next[slideId] || [];
              if (!existing.includes(note)) next[slideId] = [...existing, note];
            }
            this.slideRepairNotes = next;
          }
        }
        if (type === 'run.instruction.queued' && event.payload?.user_message && this.currentTask) {
          const userMessage = event.payload.user_message as ProjectAgentMessage;
          const messages = this.currentTask.messages || [];
          const optimisticIndex = messages.findIndex(message =>
            message.id === userMessage.id
            || (message.id.startsWith('local-') && message.run_id === userMessage.run_id && message.content === userMessage.content),
          );
          if (optimisticIndex >= 0) messages[optimisticIndex] = { ...messages[optimisticIndex], ...userMessage };
          else messages.push(userMessage);
          this.currentTask.messages = deduplicateMessages(messages);
        }
        const isCurrentRun = (!event.task_id || event.task_id === this.currentTask?.id)
          && (!event.run_id || event.run_id === this.currentTask?.active_run_id);
        if (event.status && isCurrentRun) this.pipelineStatus = event.status;
        if (this.pipelineEvents.length > 800) this.pipelineEvents.splice(0, this.pipelineEvents.length - 800);
        return;
      }
      if (type === 'project_planning_updated' && this.project) {
        this.project.planning.status = event.status || 'ready';
        this.project.planning.progress = event.progress || 0;
        if (event.status === 'ready') this.refreshTasks();
        return;
      }
      // 共享项目记忆：快照创建事件更新当前任务的记忆版本与可用来源清单。
      if (type === 'context.snapshot_created') {
        if (this.currentTask) {
          if (typeof event.memory_revision === 'number') {
            this.currentTask.memory_revision = event.memory_revision;
            this.currentTask.last_context_revision = event.memory_revision;
          }
          const manifest = (event as any).context_manifest;
          if (manifest && typeof manifest === 'object') {
            this.currentTask.available_sources = manifest.available_sources || this.currentTask.available_sources || {};
            this.currentTask.missing_optional_sources = manifest.missing_optional_sources || [];
          }
        }
        if (event.task_id && this.project) {
          const task = this.project.tasks.find(item => item.id === event.task_id);
          if (task) {
            if (typeof event.memory_revision === 'number') {
              task.memory_revision = event.memory_revision;
              task.last_context_revision = event.memory_revision;
            }
            const manifest = (event as any).context_manifest;
            if (manifest && typeof manifest === 'object') {
              task.available_sources = manifest.available_sources || task.available_sources || {};
              task.missing_optional_sources = manifest.missing_optional_sources || [];
            }
          }
        }
        return;
      }
      // 共享项目记忆：版本推进 → 刷新任务快照（获取最新 available_sources）。
      if (type === 'project_memory.updated') {
        this.refreshTasks();
        return;
      }
      if (type === 'course.metadata.updated') {
        const title = event.payload?.title || (event as any).title;
        if (title && this.project) {
          this.project.course.title = title;
          const courses = useCourseStore();
          if (courses.current?.id === this.project.course.id) courses.current.title = title;
          const index = courses.items.findIndex(item => item.id === this.project?.course.id);
          if (index >= 0) courses.items[index] = { ...courses.items[index], title } as any;
        }
        return;
      }
      // 视频生成偏好设置更新：立即刷新当前任务快照，使脚本页分辨率标签反映最新值。
      if (type === 'video_generation.setting.updated') {
        const resolution = event.payload?.resolution || (event as any).resolution;
        if (isNativeVideoResolution(resolution)) {
          this.videoResolutionEventId = Math.max(this.videoResolutionEventId, event.event_id || 0);
          // 事件由后端在设置事务提交后发出，可直接作为当前 UI 的权威增量。
          // 同步更新脚本/视频任务，避免轮询中的旧快照在异步 refresh 完成前继续显示旧值。
          if (this.project) {
            for (const task of this.project.tasks) {
              if (task.task_type === 'video_script' || task.task_type === 'video_generation') {
                task.preferred_video_resolution = resolution;
              }
            }
          }
          if (
            this.currentTask
            && (this.currentTask.task_type === 'video_script' || this.currentTask.task_type === 'video_generation')
          ) {
            this.currentTask.preferred_video_resolution = resolution;
          }
        }
        void this.refreshCurrentTask();
        return;
      }
      if (type === 'memory.source_read') {
        // 只读事件，用于时间线展示；无需额外状态变更。
        return;
      }
      if (type.startsWith('agent_initialization_') && this.project) {
        const status = type === 'agent_initialization_completed'
          ? 'ready'
          : type === 'agent_initialization_failed'
            ? 'failed'
            : event.status === 'queued' ? 'queued' : 'running';
        this.project.agent_initialization.status = status;
        this.project.agent_initialization.progress = event.progress || 0;
        this.project.agent_initialization.error = event.error || null;
        if (event.version) this.project.agent_initialization.version = event.version;
        if (type === 'agent_initialization_completed') this.refreshTasks();
        return;
      }
      if (!event.task_id || !this.project) return;
      const task = this.project.tasks.find(item => item.id === event.task_id);
      if (!task) return;

      if (event.artifact) {
        const validScope = event.artifact.course_id === task.course_id
          && event.artifact.artifact_type === task.task_type
          && (!event.task_type || event.task_type === task.task_type);
        const previousVersion = task.current_artifact?.version || 0;
        if (!validScope || event.artifact.version < previousVersion) return;
        const artifactResult = reconcileArtifact(event.artifact, task.current_artifact, 'event');
        if (artifactResult.conflict) {
          this.artifactConflict = {
            source: 'event', event_id: event.event_id, run_id: event.run_id,
            incoming_artifact_id: event.artifact.id, incoming_version: event.artifact.version,
            official_artifact_id: task.current_artifact?.id, official_version: task.current_artifact?.version,
          };
          if (this.currentTask?.id === task.id) void this.refreshCurrentTask();
          return;
        }
        task.current_artifact = artifactResult.artifact;
      }

      if (type === 'task_activity_updated' && event.phase) {
        if (task.activity_run_id !== event.run_id) {
          task.activity_run_id = event.run_id || null;
          task.activities = [];
        }
        const activity = {
          phase: event.phase,
          label: event.phase_label || event.phase,
          detail: event.detail || '',
          status: event.phase_status || 'running',
          progress: event.progress ?? task.progress,
          elapsed_ms: event.elapsed_ms || 0,
        } as NonNullable<CourseTask['current_activity']>;
        const activities = task.activities || [];
        const index = activities.findIndex(item => item.phase === activity.phase);
        if (index >= 0) activities[index] = activity;
        else activities.push(activity);
        task.activities = [...activities];
        task.current_activity = activity;
      }

      if (event.status && !['ready', 'planning'].includes(event.status)) task.status = event.status as CourseTask['status'];
      if (typeof event.progress === 'number') task.progress = event.progress;
      if (event.run_id) task.active_run_id = ['review', 'failed', 'cancelled'].includes(event.status || '') ? null : event.run_id;
      if (event.error) task.error = event.error;
      if (event.artifact) {
        task.error = null;
        task.active_run_id = null;
      }
      if (this.currentTask?.id === task.id) {
        Object.assign(this.currentTask, task);
        this.syncOfficialArtifact();
        const messages = this.currentTask.messages || [];
        if (type === 'agent_message_started' && event.message) {
          const existingIndex = messages.findIndex(message => message.id === event.message?.id || message.id.startsWith('local-'));
          if (existingIndex >= 0) {
            // 保留服务端已有 content（暂停/恢复场景避免气泡被清空后闪回）
            messages[existingIndex] = { ...messages[existingIndex], ...event.message, content: event.message.content ?? messages[existingIndex].content ?? '', status: 'streaming' };
            this.currentTask.messages = [...messages];
          } else {
            this.currentTask.messages = [...messages, { ...event.message, content: event.message.content ?? '', status: 'streaming' }];
          }
        } else if (type === 'agent_message_delta' && event.message_id) {
          let streaming = messages.find(message => message.id === event.message_id);
          if (!streaming) {
            streaming = {
              id: event.message_id,
              role: 'assistant',
              content: '',
              status: 'streaming',
              run_id: event.run_id,
            };
            this.currentTask.messages = [...messages, streaming];
          }
          streaming.content = event.reset ? (event.delta || '') : streaming.content + (event.delta || '');
          streaming.status = 'streaming';
        } else if (type === 'agent_message_completed' && event.message) {
          const existingIndex = messages.findIndex(message => message.id === event.message?.id);
          if (existingIndex >= 0) {
            messages[existingIndex] = { ...messages[existingIndex], ...event.message, status: 'completed' };
          } else {
            messages.push(event.message);
          }
          this.currentTask.messages = deduplicateMessages(messages);
          const pending = (this.currentTask.messages || []).find(
            message => message.run_id === event.message?.run_id && message.role === 'user',
          );
          if (pending) pending.status = 'completed';
        } else if (type === 'agent_message_failed' && event.message_id) {
          const existing = messages.find(message => message.id === event.message_id);
          if (existing) existing.status = 'failed';
        } else if (event.message) {
          const pending = messages.find(message => message.run_id === event.message?.run_id && message.role === 'user');
          if (pending) pending.status = 'completed';
          if (!messages.some(message => message.id === event.message?.id)) {
            this.currentTask.messages = deduplicateMessages([...messages, event.message]);
          }
        }
      }
      if (type === 'artifact_version_created' || type === 'task_dependency_stale') {
        this.refreshTasks();
        if (type === 'artifact_version_created' && this.currentTask?.id === task.id) this.refreshCurrentTask();
      }
      if (this.currentTask?.id === task.id && !['queued', 'running'].includes(task.status)) {
        this.stopActiveTaskPolling();
      }
    },
    startActiveTaskPolling(courseId: string, taskType: string) {
      this.stopActiveTaskPolling();
      const poll = async () => {
        if (this.activeTaskPollInFlight) return;
        if (!this.currentTask || this.currentTask.course_id !== courseId || this.currentTask.task_type !== taskType) {
          this.stopActiveTaskPolling();
          return;
        }
        this.activeTaskPollInFlight = true;
        try {
          const epoch = ++this.taskRequestEpoch;
          const { data } = await api.get<CourseTask>(`/courses/${courseId}/tasks/${taskType}`);
          if (epoch !== this.taskRequestEpoch) return;
          if (!this.currentTask || this.currentTask.id !== data.id) return;
          const currentArtifact = this.currentTask.current_artifact;
          const result = reconcileTaskArtifact(
            data, this.currentTask, 'poll', this.videoResolutionEventId,
          );
          const hydrated = result.task;
          if (result.conflict) {
            this.artifactConflict = { source: 'poll', task_id: data.id, incoming_artifact_id: data.current_artifact?.id };
            return;
          }
          // Status polling usually returns the same large PPT artifact. Preserve
          // its object identity so all slide previews are not rebuilt on every poll.
          if (currentArtifact?.id && hydrated.current_artifact?.id === currentArtifact.id) {
            hydrated.current_artifact = currentArtifact;
          }
          Object.assign(this.currentTask, hydrated);
          this.lastEventId = Math.max(this.lastEventId, Number(data.event_cursor || 0));
          this.syncOfficialArtifact();
          this.replaceTask(this.currentTask);
          if (!['queued', 'running'].includes(data.status)) this.stopActiveTaskPolling();
        } catch {
          // The event stream remains primary; retry transient polling failures.
        } finally {
          this.activeTaskPollInFlight = false;
        }
      };
      void poll();
      this.activeTaskPollTimer = window.setInterval(() => void poll(), 1200);
    },
    stopActiveTaskPolling() {
      if (this.activeTaskPollTimer) window.clearInterval(this.activeTaskPollTimer);
      this.activeTaskPollTimer = null;
    },
    async refreshTasks() {
      if (!this.project) return;
      const epoch = ++this.projectRequestEpoch;
      const { data } = await api.get<CourseTask[]>(`/courses/${this.project.course.id}/tasks`);
      if (epoch !== this.projectRequestEpoch || !this.project) return;
      this.project.tasks = data.map(task => reconcileTaskArtifact(
        task,
        this.project?.tasks.find(item => item.id === task.id),
        'refresh',
        this.videoResolutionEventId,
      ).task);
      if (this.currentTask) {
        const next = this.project.tasks.find(item => item.id === this.currentTask?.id);
        if (next) {
          Object.assign(this.currentTask, next);
          this.syncOfficialArtifact();
        }
      }
    },
    async refreshCurrentTask() {
      if (!this.project || !this.currentTask) return;
      const epoch = ++this.taskRequestEpoch;
      const { data } = await api.get<CourseTask>(`/courses/${this.project.course.id}/tasks/${this.currentTask.task_type}`);
      if (epoch !== this.taskRequestEpoch || !this.currentTask) return;
      const result = reconcileTaskArtifact(
        data, this.currentTask, 'refresh', this.videoResolutionEventId,
      );
      const hydrated = result.task;
      if (result.conflict) {
        this.artifactConflict = { source: 'refresh', task_id: data.id, incoming_artifact_id: data.current_artifact?.id };
        return;
      }
      Object.assign(this.currentTask, hydrated);
      this.lastEventId = Math.max(this.lastEventId, Number(data.event_cursor || 0));
      this.syncOfficialArtifact();
      this.replaceTask(this.currentTask);
    },
    async connect(courseId: string) {
      if (this.connectedCourseId === courseId && this.eventSource) return;
      if (this.connectingCourseId === courseId) return;
      this.disconnect();
      this.connectedCourseId = courseId;
      this.connectingCourseId = courseId;
      try {
        const { data } = await api.post(`/courses/${courseId}/task-events/token`);
        if (this.connectedCourseId !== courseId) return;
        const source = new EventSource(`/api/v1/courses/${courseId}/task-events?token=${encodeURIComponent(data.token)}&after=${this.lastEventId}`);
        this.eventSource = source;
        source.onopen = () => {
          this.connectionError = '';
          this.reconnectAttempt = 0;
        };
        for (const type of TASK_EVENTS) {
          source.addEventListener(type, raw => {
            try {
              this.applyEvent(type, JSON.parse((raw as MessageEvent).data));
            } catch {
              this.connectionError = '项目事件格式异常，已保留当前文件内容。';
            }
          });
        }
        source.onerror = () => {
          source.close();
          if (this.eventSource === source) this.eventSource = null;
          this.connectionError = '项目实时连接已中断，正在恢复。';
          this.scheduleReconnect(courseId);
        };
      } catch (cause) {
        this.connectionError = errorMessage(cause);
        this.scheduleReconnect(courseId);
      } finally {
        if (this.connectingCourseId === courseId) this.connectingCourseId = null;
      }
    },
    scheduleReconnect(courseId: string) {
      if (this.connectedCourseId !== courseId || this.reconnectTimer) return;
      const delay = Math.min(15000, 1000 * 2 ** this.reconnectAttempt++);
      this.reconnectTimer = window.setTimeout(() => {
        this.reconnectTimer = null;
        this.connect(courseId);
      }, delay);
    },
    disconnect() {
      this.eventSource?.close();
      this.eventSource = null;
      if (this.reconnectTimer) window.clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
      this.connectingCourseId = null;
      this.connectedCourseId = null;
    },
  },
});
