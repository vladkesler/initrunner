import { request, ApiError } from './client';
import type {
	AgentDetail,
	AgentSummary,
	IngestDocument,
	IngestSSEEvent,
	IngestStats,
	IngestSummary,
	MemoryItem,
	SessionDetail,
	SessionSummary,
	TriggerStat
} from './types';

const BASE = import.meta.env.VITE_API_URL ?? '';

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

export function deleteAgent(id: string): Promise<{ id: string; path: string }> {
	return request(`/api/agents/${id}`, { method: 'DELETE' });
}

export function getAgentTriggerStats(agentId: string): Promise<TriggerStat[]> {
	return request(`/api/agents/${agentId}/trigger-stats`);
}

// -- Ingestion ----------------------------------------------------------------

export function getIngestDocuments(agentId: string): Promise<IngestDocument[]> {
	return request(`/api/agents/${agentId}/ingest/documents`);
}

export function getIngestSummary(agentId: string): Promise<IngestSummary> {
	return request(`/api/agents/${agentId}/ingest/summary`);
}

export function deleteIngestDocument(
	agentId: string,
	source: string
): Promise<{ chunks_deleted: number }> {
	return request(
		`/api/agents/${agentId}/ingest/documents?source=${encodeURIComponent(source)}`,
		{ method: 'DELETE' }
	);
}

export function addIngestUrl(agentId: string, url: string): Promise<IngestStats> {
	return request(`/api/agents/${agentId}/ingest/add-url`, {
		method: 'POST',
		body: JSON.stringify({ url })
	});
}

export async function uploadIngestFiles(
	agentId: string,
	files: FileList
): Promise<IngestStats> {
	const formData = new FormData();
	for (const file of files) {
		formData.append('files', file);
	}
	const res = await fetch(`${BASE}/api/agents/${agentId}/ingest/upload`, {
		method: 'POST',
		body: formData
	});
	if (!res.ok) {
		const body = await res.json().catch(() => ({ detail: res.statusText }));
		throw new ApiError(res.status, body.detail ?? res.statusText);
	}
	return res.json();
}

export function streamIngest(
	agentId: string,
	force: boolean,
	callbacks: {
		onProgress: (path: string, status: string) => void;
		onResult: (stats: IngestStats) => void;
		onError: (error: string) => void;
	}
): AbortController {
	const controller = new AbortController();
	fetch(`${BASE}/api/agents/${agentId}/ingest/run?force=${force}`, {
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
