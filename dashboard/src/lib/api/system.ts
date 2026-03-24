import { request } from './client';
import type { DoctorResponse, ToolType, AuditStats } from './types';

export function runDoctor(): Promise<DoctorResponse> {
	return request('/api/system/doctor');
}

export function listToolTypes(): Promise<ToolType[]> {
	return request('/api/system/tools');
}

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
