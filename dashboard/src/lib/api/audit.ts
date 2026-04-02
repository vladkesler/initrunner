import { request } from './client';
import type { AuditRecord } from './types';

export function queryAudit(params?: {
	agent_name?: string;
	run_id?: string;
	trigger_type?: string;
	since?: string;
	until?: string;
	limit?: number;
	exclude_trigger_types?: string[];
}): Promise<AuditRecord[]> {
	const search = new URLSearchParams();
	if (params?.agent_name) search.set('agent_name', params.agent_name);
	if (params?.run_id) search.set('run_id', params.run_id);
	if (params?.trigger_type) search.set('trigger_type', params.trigger_type);
	if (params?.since) search.set('since', params.since);
	if (params?.until) search.set('until', params.until);
	if (params?.limit) search.set('limit', String(params.limit));
	if (params?.exclude_trigger_types) {
		for (const t of params.exclude_trigger_types) {
			search.append('exclude_trigger_types', t);
		}
	}
	const qs = search.toString();
	return request(`/api/audit${qs ? `?${qs}` : ''}`);
}
