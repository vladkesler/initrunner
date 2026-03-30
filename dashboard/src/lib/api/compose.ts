import { request } from './client';
import type {
	ComposeBuilderOptions,
	ComposeDetail,
	ComposeRunResponse,
	ComposeSaveResponse,
	ComposeSeedResponse,
	ComposeStats,
	ComposeSummary,
	ComposeValidateResponse,
	DelegateEvent,
	ServiceStepResponse,
	SlotAssignment
} from './types';

const BASE = import.meta.env.VITE_API_URL ?? '';

export function fetchComposeList(): Promise<ComposeSummary[]> {
	return request('/api/compose');
}

export function fetchComposeDetail(id: string): Promise<ComposeDetail> {
	return request(`/api/compose/${id}`);
}

export function fetchComposeYaml(id: string): Promise<{ yaml: string; path: string }> {
	return request(`/api/compose/${id}/yaml`);
}

export function fetchComposeEvents(
	id: string,
	filters: {
		source?: string;
		target?: string;
		status?: string;
		since?: string;
		until?: string;
		limit?: number;
	} = {}
): Promise<DelegateEvent[]> {
	const params = new URLSearchParams();
	if (filters.source) params.set('source', filters.source);
	if (filters.target) params.set('target', filters.target);
	if (filters.status) params.set('status', filters.status);
	if (filters.since) params.set('since', filters.since);
	if (filters.until) params.set('until', filters.until);
	if (filters.limit) params.set('limit', String(filters.limit));
	const qs = params.toString();
	return request(`/api/compose/${id}/events${qs ? '?' + qs : ''}`);
}

export function fetchComposeStats(id: string): Promise<ComposeStats> {
	return request(`/api/compose/${id}/stats`);
}

export function saveComposeYaml(
	id: string,
	yaml_text: string
): Promise<{ path: string; valid: boolean; issues: string[] }> {
	return request(`/api/compose/${id}/yaml`, {
		method: 'PUT',
		body: JSON.stringify({ yaml_text })
	});
}

export function fetchComposeBuilderOptions(): Promise<ComposeBuilderOptions> {
	return request('/api/compose-builder/options');
}

export function seedCompose(req: {
	mode?: 'pattern' | 'starter';
	pattern?: string;
	name: string;
	services?: SlotAssignment[];
	service_count?: number;
	shared_memory?: boolean;
	provider: string;
	model?: string | null;
	base_url?: string | null;
	api_key_env?: string | null;
	routing_strategy?: 'all' | 'keyword' | 'sense' | null;
	starter_slug?: string;
}): Promise<ComposeSeedResponse> {
	return request('/api/compose-builder/seed', {
		method: 'POST',
		body: JSON.stringify(req)
	});
}

export function validateCompose(yaml_text: string): Promise<ComposeValidateResponse> {
	return request('/api/compose-builder/validate', {
		method: 'POST',
		body: JSON.stringify({ yaml_text })
	});
}

export function saveCompose(req: {
	compose_yaml: string;
	role_yamls: Record<string, string>;
	directory: string;
	project_name: string;
	force?: boolean;
}): Promise<ComposeSaveResponse> {
	return request('/api/compose-builder/save', {
		method: 'POST',
		body: JSON.stringify(req)
	});
}

export function deleteCompose(id: string): Promise<{ id: string; path: string }> {
	return request(`/api/compose/${id}`, { method: 'DELETE' });
}

export function streamComposeRun(
	composeId: string,
	req: { prompt: string; message_history?: string | null },
	callbacks: {
		onServiceStart: (name: string) => void;
		onServiceComplete: (step: ServiceStepResponse) => void;
		onResult: (result: ComposeRunResponse) => void;
		onError: (error: string) => void;
	}
): AbortController {
	const controller = new AbortController();

	fetch(`${BASE}/api/compose/${composeId}/run/stream`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(req),
		signal: controller.signal
	})
		.then(async (res) => {
			if (!res.ok) {
				const body = await res.json().catch(() => ({ detail: res.statusText }));
				callbacks.onError(body.detail ?? res.statusText);
				return;
			}

			const reader = res.body!.getReader();
			const decoder = new TextDecoder();
			let buffer = '';

			while (true) {
				const { done, value } = await reader.read();
				if (done) break;

				buffer += decoder.decode(value, { stream: true });
				const lines = buffer.split('\n');
				buffer = lines.pop() ?? '';

				for (const line of lines) {
					if (!line.startsWith('data: ')) continue;
					try {
						const event = JSON.parse(line.slice(6));
						if (event.type === 'service_start') callbacks.onServiceStart(event.data);
						else if (event.type === 'service_complete') callbacks.onServiceComplete(event.data);
						else if (event.type === 'result') callbacks.onResult(event.data);
						else if (event.type === 'error') callbacks.onError(event.data);
					} catch {
						// skip malformed lines
					}
				}
			}
		})
		.catch((err) => {
			if (err.name !== 'AbortError') {
				callbacks.onError(String(err));
			}
		});

	return controller;
}
