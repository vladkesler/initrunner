const BASE = import.meta.env.VITE_API_URL ?? '';

class ApiError extends Error {
	constructor(
		public status: number,
		public detail: string
	) {
		super(`${status}: ${detail}`);
		this.name = 'ApiError';
	}
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
	const res = await fetch(`${BASE}${path}`, {
		headers: { 'Content-Type': 'application/json', ...init?.headers },
		...init
	});
	if (!res.ok) {
		const body = await res.json().catch(() => ({ detail: res.statusText }));
		throw new ApiError(res.status, body.detail ?? res.statusText);
	}
	return res.json();
}

export { request, ApiError };
