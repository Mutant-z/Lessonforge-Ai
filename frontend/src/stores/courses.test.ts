import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import { api } from '../api/client';
import type { Course } from '../types';
import { useCourseStore } from './courses';

vi.mock('../api/client', () => ({
  api: {
    delete: vi.fn(),
  },
}));

const course = (id: string): Course => ({
  id,
  title: `项目 ${id}`,
  subject: '物理',
  grade_level: '八年级',
  audience: '八年级学生',
  duration_minutes: 10,
  scenario: '课堂讲解',
  language: '中文',
  status: 'draft',
  current_blueprint_version: 0,
  created_at: '2026-08-03T00:00:00Z',
  updated_at: '2026-08-03T00:00:00Z',
});

describe('course store', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.mocked(api.delete).mockReset().mockResolvedValue({ data: undefined });
  });

  it('deletes a course through the API and removes it from local state', async () => {
    const store = useCourseStore();
    const first = course('course-1');
    const second = course('course-2');
    store.items = [first, second];
    store.current = first;

    await store.delete(first.id);

    expect(api.delete).toHaveBeenCalledWith('/courses/course-1');
    expect(store.items).toEqual([second]);
    expect(store.current).toBeNull();
  });

  it('keeps local state when the delete request fails', async () => {
    const store = useCourseStore();
    const first = course('course-1');
    store.items = [first];
    vi.mocked(api.delete).mockRejectedValue(new Error('网络失败'));

    await expect(store.delete(first.id)).rejects.toThrow('网络失败');

    expect(store.items).toEqual([first]);
  });
});
