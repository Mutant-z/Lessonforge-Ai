import { api } from './client';
import type { Artifact, PPTTemplateCatalog } from '../types';

export const pptTemplatesApi = {
  getCatalog: () => api.get<PPTTemplateCatalog>('/ppt-templates').then(response => response.data),
  applyTemplate: (artifactId: string, templateId: string, expectedVersion: number) =>
    api.post<{ artifact: Artifact; changed: boolean }>(`/artifacts/${artifactId}/apply-template`, {
      template_id: templateId,
      expected_version: expectedVersion,
    }).then(response => response.data),
};
