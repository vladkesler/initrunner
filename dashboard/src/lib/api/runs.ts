import { request } from './client';
import type { CostUpdateData, RunRequest, RunResponse, SSEEvent, ToolEventData, UsageData } from './types';

const BASE = import.meta.env.VITE_API_URL ?? '';

export function executeRun(req: RunRequest): Promise<RunResponse> {
	return request('/api/runs', {
		method: 'POST',
		body: JSON.stringify(req)
	});
}

export function streamRun(
	req: RunRequest,
	callbacks: {
		onToken: (text: string) => void;
		onResult: (result: RunResponse) => void;
		onError: (error: string) => void;
		onToolEvent?: (event: ToolEventData) => void;
		onUsage?: (usage: UsageData) => void;
		onCostUpdate?: (data: CostUpdateData) => void;
	}
): AbortController {
	const controller = new AbortController();

	fetch(`${BASE}/api/runs/stream`, {
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
			let gotTerminal = false;

			while (true) {
				const { done, value } = await reader.read();
				if (done) break;

				buffer += decoder.decode(value, { stream: true });
				const lines = buffer.split('\n');
				buffer = lines.pop() ?? '';

				for (const line of lines) {
					if (!line.startsWith('data: ')) continue;
					try {
						const event: SSEEvent = JSON.parse(line.slice(6));
						if (event.type === 'token') {
							callbacks.onToken(event.data);
						} else if (event.type === 'tool_event') {
							callbacks.onToolEvent?.(event.data);
						} else if (event.type === 'usage') {
							callbacks.onUsage?.(event.data);
						} else if (event.type === 'cost_update') {
							callbacks.onCostUpdate?.(event.data);
						} else if (event.type === 'result') {
							gotTerminal = true;
							callbacks.onResult(event.data);
						} else if (event.type === 'error') {
							gotTerminal = true;
							callbacks.onError(event.data);
						}
					} catch {
						// skip malformed lines
					}
				}
			}

			if (!gotTerminal) {
				callbacks.onError('Connection closed before run completed');
			}
		})
		.catch((err) => {
			if (err.name !== 'AbortError') {
				callbacks.onError(String(err));
			}
		});

	return controller;
}
