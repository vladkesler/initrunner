import { request } from './client';
import type {
	ComposeBuilderOptions,
	ComposeDetail,
	ComposeSaveResponse,
	ComposeSeedResponse,
	ComposeStats,
	ComposeSummary,
	ComposeValidateResponse,
	DelegateEvent,
	SlotAssignment
} from './types';

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
	pattern: string;
	name: string;
	services: SlotAssignment[];
	service_count: number;
	shared_memory: boolean;
	provider: string;
	model?: string | null;
	base_url?: string | null;
	api_key_env?: string | null;
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
