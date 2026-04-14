import { request } from './client';
import type { CostSummary, AgentCost, DailyCost, ModelCost, ToolCost } from './types';

export function fetchCostSummary(): Promise<CostSummary> {
	return request<CostSummary>('/api/cost/summary');
}

export function fetchCostByAgent(params?: {
	agent_name?: string;
	since?: string;
	until?: string;
}): Promise<AgentCost[]> {
	const q = new URLSearchParams();
	if (params?.agent_name) q.set('agent_name', params.agent_name);
	if (params?.since) q.set('since', params.since);
	if (params?.until) q.set('until', params.until);
	const qs = q.toString();
	return request<AgentCost[]>(`/api/cost/by-agent${qs ? `?${qs}` : ''}`);
}

export function fetchCostDaily(params?: {
	days?: number;
	agent_name?: string;
}): Promise<DailyCost[]> {
	const q = new URLSearchParams();
	if (params?.days) q.set('days', String(params.days));
	if (params?.agent_name) q.set('agent_name', params.agent_name);
	const qs = q.toString();
	return request<DailyCost[]>(`/api/cost/daily${qs ? `?${qs}` : ''}`);
}

export function fetchCostByModel(params?: {
	since?: string;
	until?: string;
}): Promise<ModelCost[]> {
	const q = new URLSearchParams();
	if (params?.since) q.set('since', params.since);
	if (params?.until) q.set('until', params.until);
	const qs = q.toString();
	return request<ModelCost[]>(`/api/cost/by-model${qs ? `?${qs}` : ''}`);
}

export function fetchCostByTool(params?: {
	agent_name?: string;
	since?: string;
	until?: string;
}): Promise<ToolCost[]> {
	const q = new URLSearchParams();
	if (params?.agent_name) q.set('agent_name', params.agent_name);
	if (params?.since) q.set('since', params.since);
	if (params?.until) q.set('until', params.until);
	const qs = q.toString();
	return request<ToolCost[]>(`/api/cost/by-tool${qs ? `?${qs}` : ''}`);
}
