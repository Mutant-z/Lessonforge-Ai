import { defineStore } from 'pinia'
import { api } from '../api/client'
import type { Course } from '../types'

export const useCourseStore = defineStore('courses', {
  state: () => ({
    items: [] as Course[],
    current: null as Course | null,
    loading: false
  }),
  actions: {
    async load() {
      this.loading = true;
      try {
        const { data } = await api.get('/courses');
        this.items = data.items || [];
      } finally {
        this.loading = false;
      }
    },
    async open(id: string) {
      const { data } = await api.get(`/courses/${id}`);
      this.current = data;
      return data;
    },
    async create(payload: any) {
      const { data } = await api.post('/courses', payload);
      this.items.unshift(data);
      return data;
    }
  }
})
