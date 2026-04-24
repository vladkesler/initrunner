import { request } from './client';
import type { PendingCall } from './types';

export interface PendingRun {
	run_id: string;
	agent_name: string;
	role_path: string | null;
	created_at: string;
	originating_prompt: string | null;
	calls: PendingCall[];
}

export interface PendingListResponse {
	runs: PendingRun[];
	count: number;
}

export interface PendingCountResponse {
	count: number;
}

export interface ApprovalsResolveRequest {
	decisions: Record<string, boolean>;
	resolved_by?: string | null;
}

export interface ApprovalsResolveResponse {
	run_id: string;
	status: 'done' | 'paused';
	success: boolean;
	output: string;
	error: string | null;
	tokens_in: number;
	tokens_out: number;
	total_tokens: number;
	duration_ms: number;
	message_history: string | null;
	pending_approvals: PendingCall[];
}

export function listPending(limit = 200): Promise<PendingListResponse> {
	return request(`/api/approvals/pending?limit=${limit}`);
}

export function countPending(): Promise<PendingCountResponse> {
	return request('/api/approvals/pending?count_only=1');
}

export function getPendingRun(runId: string): Promise<PendingRun> {
	return request(`/api/approvals/${encodeURIComponent(runId)}`);
}

export function resolveRun(
	runId: string,
	req: ApprovalsResolveRequest
): Promise<ApprovalsResolveResponse> {
	return request(`/api/approvals/${encodeURIComponent(runId)}`, {
		method: 'POST',
		body: JSON.stringify(req)
	});
}
