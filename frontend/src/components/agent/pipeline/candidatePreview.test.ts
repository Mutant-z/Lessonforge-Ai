import { describe, expect, it } from 'vitest';
import { authenticatedPreviewRequestUrl } from './candidatePreview';

describe('authenticatedPreviewRequestUrl', () => {
  it('removes the client base prefix from candidate preview URLs', () => {
    expect(authenticatedPreviewRequestUrl(
      '/api/v1/ppt-agent/runs/run-1/candidate-previews/request-1/candidate-a',
    )).toBe('/ppt-agent/runs/run-1/candidate-previews/request-1/candidate-a');
  });

  it('keeps already normalized and absolute URLs unchanged', () => {
    expect(authenticatedPreviewRequestUrl('/ppt-agent/runs/run-1/preview')).toBe(
      '/ppt-agent/runs/run-1/preview',
    );
    expect(authenticatedPreviewRequestUrl('https://example.test/preview.jpg')).toBe(
      'https://example.test/preview.jpg',
    );
  });
});
