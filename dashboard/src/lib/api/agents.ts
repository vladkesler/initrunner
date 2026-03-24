import { request } from './client';
import type { AgentDetail, AgentSummary, MemoryItem, SessionDetail, SessionSummary } from './types';

export function listAgents(): Promise<AgentSummary[]> {
	return request('/api/agents');
}

export function getAgent(id: string): Promise<AgentSummary> {
	return request(`/api/agents/${id}`);
}

export function getAgentDetail(id: string): Promise<AgentDetail> {
	return request(`/api/agents/${id}/detail`);
}

export function getAgentYaml(id: string): Promise<{ yaml: string; path: string }> {
	return request(`/api/agents/${id}/yaml`);
}

export function getAgentMemories(
	agentId: string,
	params?: { category?: string; memory_type?: string; limit?: number }
): Promise<MemoryItem[]> {
	const search = new URLSearchParams();
	if (params?.category) search.set('category', params.category);
	if (params?.memory_type) search.set('memory_type', params.memory_type);
	if (params?.limit) search.set('limit', String(params.limit));
	const qs = search.toString();
	return request(`/api/agents/${agentId}/memories${qs ? `?${qs}` : ''}`);
}

export function getAgentSessions(agentId: string, limit?: number): Promise<SessionSummary[]> {
	const qs = limit ? `?limit=${limit}` : '';
	return request(`/api/agents/${agentId}/sessions${qs}`);
}

export function getAgentSession(agentId: string, sessionId: string): Promise<SessionDetail> {
	return request(`/api/agents/${agentId}/sessions/${sessionId}`);
}

export function consolidateMemories(agentId: string): Promise<{ consolidated: number }> {
	return request(`/api/agents/${agentId}/memories/consolidate`, { method: 'POST' });
}
