import { request } from '$lib/api/client';
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
	ValidationIssue
} from './types';

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
	mode: 'blank';
	name: string;
	strategy: string;
	persona_count: number;
	personas?: PersonaSeedEntry[] | null;
	provider: string;
	model?: string | null;
	base_url?: string | null;
	api_key_env?: string | null;
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
