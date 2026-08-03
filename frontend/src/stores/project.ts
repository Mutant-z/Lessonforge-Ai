import { defineStore } from 'pinia';
import { api, errorMessage } from '../api/client';
import type { CourseProjectWorkspace, CourseTask, ProjectAgentMessage, ProjectTaskEvent } from '../types';
import { useCourseStore } from './courses';

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
  'quality_updated',
  'agent_initialization_started',
  'agent_initialization_progress',
  'agent_initialization_completed',
  'agent_initialization_failed',
];

export const useProjectStore = defineStore('project', {
  state: () => ({
    project: null as CourseProjectWorkspace | null,
    currentTask: null as CourseTask | null,
    loading: false,
    connectionError: '',
    lastEventId: 0,
    connectedCourseId: null as string | null,
    connectingCourseId: null as string | null,
    eventSource: null as EventSource | null,
    reconnectTimer: null as number | null,
    reconnectAttempt: 0,
    activeTaskPollTimer: null as number | null,
    activeTaskPollInFlight: false,
  }),
  getters: {
    tasks: state => state.project?.tasks || [],
    completion(state) {
      const tasks = state.project?.tasks || [];
      return tasks.length ? Math.round(tasks.reduce((sum, task) => sum + task.progress, 0) / tasks.length) : 0;
    },
  },
  actions: {
    async open(courseId: string) {
      this.loading = true;
      try {
        const { data } = await api.get<CourseProjectWorkspace>(`/courses/${courseId}/project`);
        this.project = data;
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
      if (!this.project || this.project.course.id !== courseId) await this.open(courseId);
      const { data } = await api.get<CourseTask>(`/courses/${courseId}/tasks/${taskType}`);
      this.currentTask = data;
      this.replaceTask(data);
      if (['queued', 'running'].includes(data.status)) this.startActiveTaskPolling(courseId, taskType);
      else this.stopActiveTaskPolling();
      return data;
    },
    replaceTask(task: CourseTask) {
      if (!this.project) return;
      const index = this.project.tasks.findIndex(item => item.id === task.id);
      if (index >= 0) this.project.tasks[index] = { ...this.project.tasks[index], ...task };
    },
    async sendMessage(courseId: string, taskType: string, content: string) {
      const local: ProjectAgentMessage = {
        id: `local-${crypto.randomUUID()}`,
        role: 'user',
        content,
        status: 'pending',
      };
      if (this.currentTask) this.currentTask.messages = [...(this.currentTask.messages || []), local];
      try {
        const { data } = await api.post(`/courses/${courseId}/tasks/${taskType}/messages`, { content });
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
    async runTask(courseId: string, taskType: string, action: 'initial' | 'retry' | 'sync_dependencies' | 'sync_context') {
      const { data } = await api.post(`/courses/${courseId}/tasks/${taskType}/runs`, { action });
      await this.openTask(courseId, taskType);
      this.startActiveTaskPolling(courseId, taskType);
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
      this.currentTask = { ...(this.currentTask || data), ...data };
      this.replaceTask(data);
      return data;
    },
    async setTaskModel(courseId: string, taskType: string, modelConfigId: string) {
      const { data } = await api.patch(`/courses/${courseId}/tasks/${taskType}/model`, { model_config_id: modelConfigId });
      if (this.currentTask) this.currentTask.model_config_id = data.model_config_id;
      return data;
    },
    applyEvent(type: string, event: ProjectTaskEvent) {
      if (event.event_id && event.event_id <= this.lastEventId) return;
      this.lastEventId = Math.max(this.lastEventId, event.event_id || 0);
      if (type === 'project_planning_updated' && this.project) {
        this.project.planning.status = event.status || 'ready';
        this.project.planning.progress = event.progress || 0;
        if (event.status === 'ready') this.refreshTasks();
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
        task.current_artifact = event.artifact;
        task.error = null;
        task.active_run_id = null;
      }
      if (this.currentTask?.id === task.id) {
        Object.assign(this.currentTask, task);
        const messages = this.currentTask.messages || [];
        if (type === 'agent_message_started' && event.message) {
          const existing = messages.find(message => message.id === event.message?.id);
          if (existing) Object.assign(existing, event.message, { content: '', status: 'streaming' });
          else this.currentTask.messages = [...messages, { ...event.message, content: '', status: 'streaming' }];
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
          const existing = messages.find(message => message.id === event.message?.id);
          if (existing) Object.assign(existing, event.message, { status: 'completed' });
          else this.currentTask.messages = [...messages, event.message];
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
          if (!messages.some(message => message.id === event.message?.id || (message.role === event.message?.role && message.content === event.message?.content))) {
            this.currentTask.messages = [...messages, event.message];
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
          const { data } = await api.get<CourseTask>(`/courses/${courseId}/tasks/${taskType}`);
          if (!this.currentTask || this.currentTask.id !== data.id) return;
          this.currentTask = data;
          this.replaceTask(data);
          if (!['queued', 'running'].includes(data.status)) this.stopActiveTaskPolling();
        } catch {
          // The event stream remains primary; retry transient polling failures.
        } finally {
          this.activeTaskPollInFlight = false;
        }
      };
      void poll();
      this.activeTaskPollTimer = window.setInterval(() => void poll(), 600);
    },
    stopActiveTaskPolling() {
      if (this.activeTaskPollTimer) window.clearInterval(this.activeTaskPollTimer);
      this.activeTaskPollTimer = null;
    },
    async refreshTasks() {
      if (!this.project) return;
      const { data } = await api.get<CourseTask[]>(`/courses/${this.project.course.id}/tasks`);
      this.project.tasks = data;
      if (this.currentTask) {
        const next = data.find(item => item.id === this.currentTask?.id);
        if (next) Object.assign(this.currentTask, next);
      }
    },
    async refreshCurrentTask() {
      if (!this.project || !this.currentTask) return;
      const { data } = await api.get<CourseTask>(`/courses/${this.project.course.id}/tasks/${this.currentTask.task_type}`);
      this.currentTask = data;
      this.replaceTask(data);
    },
    async connect(courseId: string) {
      if (this.connectedCourseId === courseId && this.eventSource) return;
      if (this.connectingCourseId === courseId) return;
      if (this.connectedCourseId && this.connectedCourseId !== courseId) this.lastEventId = 0;
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
