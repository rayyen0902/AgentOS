const ADMIN_KEY = 'admin-key-placeholder'; // TODO: load from env or auth context

export async function adminFetch(url: string, options: RequestInit = {}): Promise<Response> {
  return fetch(url, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      'X-Admin-Key': ADMIN_KEY,
      ...(options.headers || {}),
    },
  });
}
