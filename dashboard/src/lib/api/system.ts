import { request } from './client';
import type { DoctorResponse, ToolType, AuditStats } from './types';

export function runDoctor(): Promise<DoctorResponse> {
	return request('/api/system/doctor');
}

export function listToolTypes(): Promise<ToolType[]> {
	return request('/api/system/tools');
}

// -- Default model -----------------------------------------------------------

export interface DefaultModelResponse {
	provider: string;
	model: string;
	base_url: string | null;
	api_key_env: string | null;
	source: 'initrunner_model_env' | 'run_yaml' | 'auto_detected' | 'none';
}

export function getDefaultModel(): Promise<DefaultModelResponse> {
	return request('/api/system/default-model');
}

export function saveDefaultModel(body: {
	provider: string;
	model: string;
	base_url?: string | null;
	api_key_env?: string | null;
}): Promise<DefaultModelResponse> {
	return request('/api/system/default-model', {
		method: 'POST',
		body: JSON.stringify(body)
	});
}

export function resetDefaultModel(): Promise<DefaultModelResponse> {
	return request('/api/system/default-model', { method: 'DELETE' });
}

// -- Audit stats --------------------------------------------------------------

export function fetchAuditStats(params?: {
	agent_name?: string;
	since?: string;
	until?: string;
}): Promise<AuditStats> {
	const search = new URLSearchParams();
	if (params?.agent_name) search.set('agent_name', params.agent_name);
	if (params?.since) search.set('since', params.since);
	if (params?.until) search.set('until', params.until);
	const qs = search.toString();
	return request(`/api/audit/stats${qs ? `?${qs}` : ''}`);
}
