import { defineStore } from 'pinia';
import { api } from '../api/client';
import type { IntakeDraftUpdatedEvent, IntakeMaterial, IntakeMessage, IntakeSession, IntakeTurnFailure } from '../types';

export const useCourseIntakeStore = defineStore('course-intake', {
  state: () => ({
    session: null as IntakeSession | null,
    messages: [] as IntakeMessage[],
    materials: [] as IntakeMaterial[],
    lastFailure: null as IntakeTurnFailure | null,
    loading: false,
    sending: false,
    confirming: false,
  }),
  actions: {
    async create(modelConfigId?: string | null) {
      const { data } = await api.post<IntakeSession>('/course-intakes', {
        model_config_id: modelConfigId || null,
      });
      this.session = data;
      this.messages = [];
      this.materials = [];
      this.lastFailure = null;
      return data;
    },
    async open(id: string) {
      this.loading = true;
      try {
        const [session, messages, materials] = await Promise.all([
          api.get<IntakeSession>(`/course-intakes/${id}`),
          api.get<IntakeMessage[]>(`/course-intakes/${id}/messages`),
          api.get<IntakeMaterial[]>(`/course-intakes/${id}/materials`),
        ]);
        this.session = session.data;
        this.messages = messages.data;
        this.materials = materials.data;
        this.lastFailure = session.data.last_failure || null;
        return session.data;
      } finally {
        this.loading = false;
      }
    },
    async refresh() {
      if (!this.session) return;
      await this.open(this.session.id);
    },
    async upload(file: File) {
      if (!this.session) throw new Error('需求会话尚未创建');
      const body = new FormData();
      body.append('file', file);
      body.append('usage_policy', 'priority_reference');
      const { data } = await api.post<IntakeMaterial>(`/course-intakes/${this.session.id}/materials`, body);
      this.materials.push(data);
      return data;
    },
    async send(content: string) {
      if (!this.session) throw new Error('需求会话尚未创建');
      this.sending = true;
      try {
        const { data } = await api.post<{ turn_id: string }>(`/course-intakes/${this.session.id}/messages`, {
          content,
          expected_revision: this.session.current_revision,
        });
        this.messages.push({ id: `local-${data.turn_id}`, turn_id: data.turn_id, role: 'user', content });
        this.session.status = 'processing';
        this.session.active_turn_id = data.turn_id;
        this.session.last_failure = null;
        this.lastFailure = null;
        return data.turn_id;
      } finally {
        this.sending = false;
      }
    },
    applyDraftUpdate(event: IntakeDraftUpdatedEvent) {
      if (!this.session) return;
      this.session.current_revision = event.revision;
      this.session.draft = event.draft;
      this.session.field_sources = event.field_sources;
      this.session.missing_fields = event.missing_fields;
      this.session.assumptions = event.assumptions;
      this.session.conflicts = event.conflicts;
      this.session.status = event.ready_to_confirm ? 'ready' : 'collecting';
      this.session.last_failure = null;
      this.lastFailure = null;
    },
    finishAssistant(turnId: string, content: string) {
      if (!this.messages.some(message => message.turn_id === turnId && message.role === 'assistant')) {
        this.messages.push({ id: `assistant-${turnId}`, turn_id: turnId, role: 'assistant', content });
      }
      if (this.session) {
        this.session.active_turn_id = null;
        this.session.last_failure = null;
      }
      this.lastFailure = null;
    },
    failTurn(failure: IntakeTurnFailure) {
      this.lastFailure = failure;
      if (!this.session) return;
      this.session.active_turn_id = null;
      this.session.last_failure = failure;
      this.session.status = failure.session_status || 'collecting';
    },
    async retryFailedTurn() {
      if (!this.session || !this.lastFailure) throw new Error('没有可重试的需求分析任务');
      this.sending = true;
      try {
        const { data } = await api.post<{ turn_id: string; status: string }>(
          `/course-intakes/turns/${this.lastFailure.turn_id}/retry`,
        );
        this.session.status = 'processing';
        this.session.active_turn_id = data.turn_id;
        this.session.last_failure = null;
        this.lastFailure = null;
        return data.turn_id;
      } finally {
        this.sending = false;
      }
    },
    async patchField(field: string, value: unknown) {
      if (!this.session) return;
      const { data } = await api.patch<IntakeSession>(`/course-intakes/${this.session.id}/draft`, {
        field,
        value,
        expected_revision: this.session.current_revision,
      });
      this.session = data;
    },
    async setModel(modelConfigId: string) {
      if (!this.session) throw new Error('需求会话尚未创建');
      const { data } = await api.patch<IntakeSession>(`/course-intakes/${this.session.id}/model`, {
        model_config_id: modelConfigId,
      });
      this.session = data;
      return data;
    },
    async confirm() {
      if (!this.session) throw new Error('需求会话尚未创建');
      this.confirming = true;
      const storageKey = `lf_intake_confirm_${this.session.id}`;
      let idempotencyKey = localStorage.getItem(storageKey);
      if (!idempotencyKey) {
        idempotencyKey = crypto.randomUUID();
        localStorage.setItem(storageKey, idempotencyKey);
      }
      try {
        const { data } = await api.post<{ course_id: string; run_id: string; planning_run_id: string; project_status: string }>(`/course-intakes/${this.session.id}/confirm`, {
          expected_revision: this.session.current_revision,
          idempotency_key: idempotencyKey,
        });
        this.session.status = 'completed';
        this.session.course_id = data.course_id;
        return data;
      } finally {
        this.confirming = false;
      }
    },
  },
});
