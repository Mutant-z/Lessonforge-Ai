/** Normalize an API URL for the shared Axios client whose baseURL is /api/v1. */
export function authenticatedPreviewRequestUrl(value: string): string {
  return value.startsWith('/api/v1/') ? value.slice('/api/v1'.length) : value;
}

