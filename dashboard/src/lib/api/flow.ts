import { request } from './client';
import type {
	FlowBuilderOptions,
	FlowDetail,
	FlowRunResponse,
	FlowSaveResponse,
	FlowSeedResponse,
	FlowStats,
	FlowSummary,
	FlowValidateResponse,
	DelegateEvent,
	AgentStepResponse,
	SlotAssignment,
	TimelineResponse,
	ToolEventData
} from './types';

const BASE = import.meta.env.VITE_API_URL ?? '';

export function fetchFlowList(): Promise<FlowSummary[]> {
	return request('/api/flows');
}

export function fetchFlowDetail(id: string): Promise<FlowDetail> {
	return request(`/api/flows/${id}`);
}

export function fetchFlowYaml(id: string): Promise<{ yaml: string; path: string }> {
	return request(`/api/flows/${id}/yaml`);
}

export function fetchFlowEvents(
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
	return request(`/api/flows/${id}/events${qs ? '?' + qs : ''}`);
}

export function fetchFlowStats(id: string): Promise<FlowStats> {
	return request(`/api/flows/${id}/stats`);
}

export function saveFlowYaml(
	id: string,
	yaml_text: string
): Promise<{ path: string; valid: boolean; issues: string[] }> {
	return request(`/api/flows/${id}/yaml`, {
		method: 'PUT',
		body: JSON.stringify({ yaml_text })
	});
}

export function fetchFlowBuilderOptions(): Promise<FlowBuilderOptions> {
	return request('/api/flow-builder/options');
}

export function seedFlow(req: {
	mode?: 'pattern' | 'starter';
	pattern?: string;
	name: string;
	agents?: SlotAssignment[];
	agent_count?: number;
	shared_memory?: boolean;
	provider: string;
	model?: string | null;
	base_url?: string | null;
	api_key_env?: string | null;
	routing_strategy?: 'all' | 'keyword' | 'sense' | null;
	starter_slug?: string;
}): Promise<FlowSeedResponse> {
	return request('/api/flow-builder/seed', {
		method: 'POST',
		body: JSON.stringify(req)
	});
}

export function validateFlow(yaml_text: string): Promise<FlowValidateResponse> {
	return request('/api/flow-builder/validate', {
		method: 'POST',
		body: JSON.stringify({ yaml_text })
	});
}

export function saveFlow(req: {
	flow_yaml: string;
	role_yamls: Record<string, string>;
	directory: string;
	project_name: string;
	force?: boolean;
}): Promise<FlowSaveResponse> {
	return request('/api/flow-builder/save', {
		method: 'POST',
		body: JSON.stringify(req)
	});
}

export function deleteFlow(id: string): Promise<{ id: string; path: string }> {
	return request(`/api/flows/${id}`, { method: 'DELETE' });
}

export function streamFlowRun(
	flowId: string,
	req: { prompt: string; message_history?: string | null },
	callbacks: {
		onAgentStart: (name: string) => void;
		onAgentComplete: (step: AgentStepResponse) => void;
		onToolEvent?: (data: ToolEventData) => void;
		onResult: (result: FlowRunResponse) => void;
		onError: (error: string) => void;
	}
): AbortController {
	const controller = new AbortController();

	fetch(`${BASE}/api/flows/${flowId}/run/stream`, {
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
						if (event.type === 'agent_start') callbacks.onAgentStart(event.data);
						else if (event.type === 'agent_complete') callbacks.onAgentComplete(event.data);
						else if (event.type === 'tool_event') callbacks.onToolEvent?.(event.data);
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

export function fetchFlowTimeline(
	flowId: string,
	since?: string,
	until?: string
): Promise<TimelineResponse> {
	const params = new URLSearchParams();
	if (since) params.set('since', since);
	if (until) params.set('until', until);
	const qs = params.toString();
	return request(`/api/flows/${flowId}/timeline${qs ? `?${qs}` : ''}`);
}
