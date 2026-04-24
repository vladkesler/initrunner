import {
	countPending,
	listPending,
	resolveRun,
	type ApprovalsResolveResponse,
	type PendingRun
} from '$lib/api/approvals';
import { ApiError } from '$lib/api/client';
import { toast } from './toast.svelte';
import { startedRuns } from './startedRuns.svelte';

const POLL_INTERVAL_MS = 20_000;

let count = $state(0);
let runs = $state<PendingRun[]>([]);
let loaded = $state(false); // true after first successful load
let error = $state<string | null>(null);
let pollTimer: ReturnType<typeof setInterval> | null = null;
let subscribers = 0;

async function refreshList(): Promise<void> {
	try {
		const resp = await listPending();
		const previous = new Set(runs.map((r) => r.run_id));
		runs = resp.runs;
		count = resp.count;
		loaded = true;
		error = null;
		// Absent-Kicker toast: if a run the user started just appeared, nudge them.
		for (const run of resp.runs) {
			if (!previous.has(run.run_id) && startedRuns.has(run.run_id)) {
				const short = run.run_id.slice(0, 8);
				toast.info(`Run ${short} paused, approval needed (/approvals/${run.run_id}).`);
			}
		}
	} catch (e) {
		error = e instanceof Error ? e.message : String(e);
	}
}

async function refreshCount(): Promise<void> {
	try {
		const resp = await countPending();
		count = resp.count;
	} catch {
		// swallow — next tick retries. Never surface noise for a background poll.
	}
}

function startPolling(): void {
	if (pollTimer !== null) return;
	pollTimer = setInterval(refreshCount, POLL_INTERVAL_MS);
}

function stopPolling(): void {
	if (pollTimer !== null) {
		clearInterval(pollTimer);
		pollTimer = null;
	}
}

/**
 * Hook into the approvals state. Starts background polling on first
 * subscription and stops when the last caller unsubscribes. Returns a
 * cleanup to release the subscription.
 */
export function subscribeApprovals(): () => void {
	subscribers++;
	if (subscribers === 1) {
		void refreshCount();
		startPolling();
	}
	return () => {
		subscribers--;
		if (subscribers === 0) {
			stopPolling();
		}
	};
}

export const approvals = {
	get count(): number {
		return count;
	},
	get runs(): PendingRun[] {
		return runs;
	},
	get loaded(): boolean {
		return loaded;
	},
	get error(): string | null {
		return error;
	},
	/** Bump the count on an SSE `approval_required` event. Does not re-fetch. */
	bumpOnSseApproval(runId: string, pendingCount = 1): void {
		count = count + pendingCount;
		void refreshList();
		// Surface via nav badge + toast if the run belongs to this session.
		if (startedRuns.has(runId)) {
			const short = runId.slice(0, 8);
			toast.info(`Run ${short} paused, approval needed.`);
		}
	},
	/** Force a full list refresh. Called by the queue page on mount and after resolve. */
	refresh: refreshList,
	/** Submit decisions for a paused run. Removes the row on success, updates on re-pause. */
	async submit(
		runId: string,
		decisions: Record<string, boolean>,
		resolvedBy?: string
	): Promise<ApprovalsResolveResponse> {
		try {
			const resp = await resolveRun(runId, { decisions, resolved_by: resolvedBy });
			if (resp.status === 'done') {
				runs = runs.filter((r) => r.run_id !== runId);
				count = Math.max(0, count - Object.keys(decisions).length);
			} else {
				// Re-paused with new calls. Refresh to pick up the new row shape.
				await refreshList();
			}
			return resp;
		} catch (e) {
			if (e instanceof ApiError && e.status === 404) {
				// Race: someone else resolved it first.
				runs = runs.filter((r) => r.run_id !== runId);
				await refreshCount();
				toast.info('Already resolved.');
			}
			throw e;
		}
	}
};
