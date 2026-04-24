/**
 * Session-local registry of run_ids the user kicked off in this tab.
 *
 * The Absent-Kicker path needs a way to distinguish "my paused run" from
 * "someone else's paused run" without a connected SSE stream. When a new
 * pending-approval row appears during polling and its run_id is in here,
 * we fire a toast linking back to the queue; otherwise the nav badge is
 * the only signal. The registry resets on page reload — that matches the
 * user's mental model of a fresh tab session.
 */

const MAX_SIZE = 200;

let ids = $state<string[]>([]);

export const startedRuns = {
	add(runId: string): void {
		if (!runId || ids.includes(runId)) return;
		ids.push(runId);
		if (ids.length > MAX_SIZE) {
			ids.shift();
		}
	},
	has(runId: string): boolean {
		return ids.includes(runId);
	},
	clear(): void {
		ids = [];
	}
};
