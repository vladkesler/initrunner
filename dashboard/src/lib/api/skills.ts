import { request } from '$lib/api/client';
import type { SkillSummary, SkillDetail } from './types';

export function listSkills(params?: {
	scope?: string;
	search?: string;
}): Promise<SkillSummary[]> {
	const q = new URLSearchParams();
	if (params?.scope) q.set('scope', params.scope);
	if (params?.search) q.set('search', params.search);
	const qs = q.toString();
	return request(`/api/skills${qs ? `?${qs}` : ''}`);
}

export function getSkillDetail(id: string): Promise<SkillDetail> {
	return request(`/api/skills/${id}`);
}

export function getSkillContent(id: string): Promise<{ content: string; path: string }> {
	return request(`/api/skills/${id}/content`);
}

export function saveSkillContent(
	id: string,
	content: string
): Promise<{ path: string; valid: boolean; issues: string[] }> {
	return request(`/api/skills/${id}/content`, {
		method: 'PUT',
		body: JSON.stringify({ content })
	});
}

export function createSkill(req: {
	name: string;
	directory: string;
	provider?: string;
}): Promise<{ id: string; path: string; name: string }> {
	return request('/api/skills', {
		method: 'POST',
		body: JSON.stringify(req)
	});
}

export function deleteSkill(id: string): Promise<{ id: string; path: string }> {
	return request(`/api/skills/${id}`, { method: 'DELETE' });
}

export function refreshSkills(): Promise<SkillSummary[]> {
	return request('/api/skills/refresh', { method: 'POST' });
}

export function getSkillDirectories(): Promise<string[]> {
	return request('/api/skills/directories');
}
