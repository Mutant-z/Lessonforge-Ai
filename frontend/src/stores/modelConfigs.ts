import { defineStore } from 'pinia';
import { settingsApi } from '../api/settings';
import type { ModelConfigItem } from '../types/settings';

export const useModelConfigStore = defineStore('model-configs', {
  state: () => ({
    configs: [] as ModelConfigItem[],
    loading: false,
    loaded: false,
    error: '',
  }),
  getters: {
    activeConfig: state => state.configs.find(item => item.is_active) || state.configs[0] || null,
  },
  actions: {
    setConfigs(configs: ModelConfigItem[]) {
      this.configs = configs;
      this.loaded = true;
      this.error = '';
    },
    async load(force = false) {
      if (this.loaded && !force) return this.configs;
      this.loading = true;
      this.error = '';
      try {
        const settings = await settingsApi.getSettings();
        this.setConfigs(settings.configs);
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
