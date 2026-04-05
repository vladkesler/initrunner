import { request, ApiError } from '$lib/api/client';
import type {
	TeamSummary,
	TeamDetail,
	TeamRunResponse,
	PersonaStepResponse,
	TeamBuilderOptions,
	TeamSeedResponse,
	TeamValidateResponse,
	TeamSaveResponse,
	PersonaSeedEntry,
	ValidationIssue,
	MemoryItem,
	IngestDocument,
	IngestSummary,
	IngestSSEEvent,
	IngestStats,
	TimelineResponse
} from './types';

const BASE = import.meta.env.VITE_API_URL ?? '';

export function fetchTeamList(): Promise<TeamSummary[]> {
	return request<TeamSummary[]>('/api/teams');
}

export function fetchTeamDetail(id: string): Promise<TeamDetail> {
	return request<TeamDetail>(`/api/teams/${id}`);
}

export function fetchTeamYaml(id: string): Promise<{ yaml: string; path: string }> {
	return request<{ yaml: string; path: string }>(`/api/teams/${id}/yaml`);
}

export function saveTeamYaml(
	id: string,
	yaml_text: string
): Promise<{ path: string; valid: boolean; issues: string[] }> {
	return request(`/api/teams/${id}/yaml`, {
		method: 'PUT',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ yaml_text })
	});
}

export function fetchTeamBuilderOptions(): Promise<TeamBuilderOptions> {
	return request<TeamBuilderOptions>('/api/team-builder/options');
}

export function seedTeam(req: {
	mode: 'blank' | 'starter';
	name: string;
	strategy?: string;
	persona_count?: number;
	personas?: PersonaSeedEntry[] | null;
	provider: string;
	model?: string | null;
	base_url?: string | null;
	api_key_env?: string | null;
	debate_max_rounds?: number;
	debate_synthesize?: boolean;
	starter_slug?: string;
}): Promise<TeamSeedResponse> {
	return request<TeamSeedResponse>('/api/team-builder/seed', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(req)
	});
}

export function validateTeam(yaml_text: string): Promise<TeamValidateResponse> {
	return request<TeamValidateResponse>('/api/team-builder/validate', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ yaml_text })
	});
}

export function saveTeam(req: {
	yaml_text: string;
	directory: string;
	filename: string;
	force?: boolean;
}): Promise<TeamSaveResponse> {
	return request<TeamSaveResponse>('/api/team-builder/save', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(req)
	});
}

export function deleteTeam(id: string): Promise<{ id: string; path: string }> {
	return request(`/api/teams/${id}`, { method: 'DELETE' });
}

export function streamTeamRun(
	teamId: string,
	req: { prompt: string },
	callbacks: {
		onPersonaStart?: (name: string) => void;
		onPersonaComplete?: (step: PersonaStepResponse) => void;
		onResult?: (result: TeamRunResponse) => void;
		onError?: (error: string) => void;
	}
): AbortController {
	const controller = new AbortController();

	fetch(`/api/teams/${teamId}/run/stream`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(req),
		signal: controller.signal
	})
		.then(async (res) => {
			if (!res.ok) {
				const text = await res.text();
				callbacks.onError?.(text || `HTTP ${res.status}`);
				return;
			}
			const reader = res.body?.getReader();
			if (!reader) return;

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
						if (event.type === 'persona_start') {
							callbacks.onPersonaStart?.(event.data);
						} else if (event.type === 'persona_complete') {
							callbacks.onPersonaComplete?.(event.data);
						} else if (event.type === 'result') {
							callbacks.onResult?.(event.data);
						} else if (event.type === 'error') {
							callbacks.onError?.(event.data);
						}
					} catch {
						// skip malformed events
					}
				}
			}
		})
		.catch((err) => {
			if (err.name !== 'AbortError') {
				callbacks.onError?.(err.message ?? 'Stream failed');
			}
		});

	return controller;
}

// -- Team Memory ---------------------------------------------------------------

export function getTeamMemories(
	teamId: string,
	params?: { category?: string; memory_type?: string; limit?: number }
): Promise<MemoryItem[]> {
	const search = new URLSearchParams();
	if (params?.category) search.set('category', params.category);
	if (params?.memory_type) search.set('memory_type', params.memory_type);
	if (params?.limit) search.set('limit', String(params.limit));
	const qs = search.toString();
	return request<MemoryItem[]>(`/api/teams/${teamId}/memories${qs ? `?${qs}` : ''}`);
}

export function consolidateTeamMemories(teamId: string): Promise<{ consolidated: number }> {
	return request(`/api/teams/${teamId}/memories/consolidate`, { method: 'POST' });
}

// -- Team Ingest ---------------------------------------------------------------

export function getTeamIngestDocuments(teamId: string): Promise<IngestDocument[]> {
	return request<IngestDocument[]>(`/api/teams/${teamId}/ingest/documents`);
}

export function getTeamIngestSummary(teamId: string): Promise<IngestSummary> {
	return request<IngestSummary>(`/api/teams/${teamId}/ingest/summary`);
}

export function deleteTeamIngestDocument(
	teamId: string,
	source: string
): Promise<{ chunks_deleted: number }> {
	return request(`/api/teams/${teamId}/ingest/documents?source=${encodeURIComponent(source)}`, {
		method: 'DELETE'
	});
}

export function addTeamIngestUrl(teamId: string, url: string): Promise<IngestStats> {
	return request(`/api/teams/${teamId}/ingest/add-url`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ url })
	});
}

export async function uploadTeamIngestFiles(teamId: string, files: FileList): Promise<IngestStats> {
	const formData = new FormData();
	for (const file of files) {
		formData.append('files', file);
	}
	const res = await fetch(`${BASE}/api/teams/${teamId}/ingest/upload`, {
		method: 'POST',
		body: formData
	});
	if (!res.ok) {
		const body = await res.json().catch(() => ({ detail: res.statusText }));
		throw new ApiError(res.status, body.detail ?? res.statusText);
	}
	return res.json();
}

export function streamTeamIngest(
	teamId: string,
	force: boolean,
	callbacks: {
		onProgress: (path: string, status: string) => void;
		onResult: (stats: IngestStats) => void;
		onError: (error: string) => void;
	}
): AbortController {
	const controller = new AbortController();
	fetch(`${BASE}/api/teams/${teamId}/ingest/run?force=${force}`, {
		method: 'POST',
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

				const parts = buffer.split('\n\n');
				buffer = parts.pop()!;

				for (const part of parts) {
					if (!part.startsWith('data: ')) continue;
					try {
						const event: IngestSSEEvent = JSON.parse(part.slice(6));
						if (event.type === 'progress') {
							callbacks.onProgress(event.data.path, event.data.status);
						} else if (event.type === 'result') {
							callbacks.onResult(event.data);
						} else if (event.type === 'error') {
							callbacks.onError(event.data);
						}
					} catch {
						// skip malformed events
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

export function fetchTeamTimeline(
	teamId: string,
	since?: string,
	until?: string
): Promise<TimelineResponse> {
	const params = new URLSearchParams();
	if (since) params.set('since', since);
	if (until) params.set('until', until);
	const qs = params.toString();
	return request(`/api/teams/${teamId}/timeline${qs ? `?${qs}` : ''}`);
}
