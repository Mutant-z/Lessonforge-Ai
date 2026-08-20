import { defineStore } from 'pinia';
import { settingsApi } from '../api/settings';
import type { ModelCategory, ModelConfigItem } from '../types/settings';

export const useModelConfigStore = defineStore('model-configs', {
  state: () => ({
    configs: [] as ModelConfigItem[],
    loading: false,
    loaded: false,
    error: '',
    activeConfigIds: { text: null, vision: null, video: null } as Record<ModelCategory, string | null>,
  }),
  getters: {
    activeConfig: state => state.configs.find(item => item.model_category === 'text' && item.is_active)
      || state.configs.find(item => item.model_category === 'text') || null,
    activeConfigFor: state => (category: ModelCategory) => (
      state.configs.find(item => item.model_category === category && item.is_active) || null
    ),
  },
  actions: {
    setConfigs(configs: ModelConfigItem[], activeConfigIds?: Partial<Record<ModelCategory, string | null>>) {
      this.configs = configs;
      for (const category of ['text', 'vision', 'video'] as ModelCategory[]) {
        this.activeConfigIds[category] = activeConfigIds?.[category]
          || configs.find(item => item.model_category === category && item.is_active)?.id
          || null;
      }
      this.loaded = true;
      this.error = '';
    },
    async load(force = false) {
      if (this.loaded && !force) return this.configs;
      this.loading = true;
      this.error = '';
      try {
        const settings = await settingsApi.getSettings();
        this.setConfigs(settings.configs, settings.active_config_ids);
        return this.configs;
      } catch (cause: any) {
        this.error = cause?.response?.data?.detail || cause?.message || '无法加载模型配置';
        throw cause;
      } finally {
        this.loading = false;
      }
    },
  },
});
