<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { Button } from '$lib/components/ui/button';
	import { toast } from '$lib/stores/toast.svelte';
	import { setCrumbs } from '$lib/stores/breadcrumb.svelte';
	import { approvals, subscribeApprovals } from '$lib/stores/approvals.svelte';
	import ApprovalsQueue from '$lib/components/approvals/ApprovalsQueue.svelte';
	import ApprovalDrawer from '$lib/components/approvals/ApprovalDrawer.svelte';
	import type { PendingRun } from '$lib/api/approvals';

	let selection = $state(new Set<string>());
	let submittingIds = $state(new Set<string>());
	let confirmingBulk = $state<null | 'approve' | 'deny'>(null);
	let confirmTimer: ReturnType<typeof setTimeout> | null = null;
	let drawerRunId = $state<string | null>(null);

	$effect(() => {
		setCrumbs([{ label: 'Approvals' }]);
	});

	// React to /approvals/{run_id} deep links.
	$effect(() => {
		const runId = page.url.pathname.startsWith('/approvals/')
			? page.url.pathname.slice('/approvals/'.length)
			: null;
		drawerRunId = runId || null;
	});

	onMount(() => {
		const unsub = subscribeApprovals();
		void approvals.refresh();
		return () => {
			unsub();
			if (confirmTimer) clearTimeout(confirmTimer);
		};
	});

	async function resolveOne(run: PendingRun, decision: boolean): Promise<void> {
		if (run.calls.length !== 1) return;
		const runId = run.run_id;
		submittingIds = new Set([...submittingIds, runId]);
		try {
			const resp = await approvals.submit(
				runId,
				{ [run.calls[0].tool_call_id]: decision }
			);
			if (resp.status === 'done') {
				toast.success(
					`${decision ? 'Approved' : 'Denied'} ${run.calls[0].tool_name} on ${run.agent_name}`
				);
			} else {
				toast.info(`Run ${runId.slice(0, 8)} paused again (${resp.pending_approvals.length} new)`);
			}
		} catch (e) {
			if (e && typeof e === 'object' && 'status' in e && e.status === 404) {
				// handled by store
			} else {
				toast.error(e instanceof Error ? e.message : String(e));
			}
		} finally {
			const next = new Set(submittingIds);
			next.delete(runId);
			submittingIds = next;
		}
	}

	function startBulk(decision: 'approve' | 'deny'): void {
		if (selection.size === 0) return;
		if (confirmingBulk !== decision) {
			confirmingBulk = decision;
			if (confirmTimer) clearTimeout(confirmTimer);
			confirmTimer = setTimeout(() => {
				confirmingBulk = null;
			}, 4000);
			return;
		}
		void commitBulk(decision);
	}

	async function commitBulk(decision: 'approve' | 'deny'): Promise<void> {
		confirmingBulk = null;
		if (confirmTimer) clearTimeout(confirmTimer);
		const ids = Array.from(selection);
		const runsSnapshot = approvals.runs.filter((r) => ids.includes(r.run_id));
		selection = new Set();
		submittingIds = new Set([...submittingIds, ...ids]);
		let okCount = 0;
		for (const run of runsSnapshot) {
			if (run.calls.length !== 1) continue;
			try {
				await approvals.submit(
					run.run_id,
					{ [run.calls[0].tool_call_id]: decision === 'approve' }
				);
				okCount++;
			} catch {
				// store will toast individual failures
			}
		}
		const next = new Set(submittingIds);
		for (const id of ids) next.delete(id);
		submittingIds = next;
		if (okCount > 0) {
			toast.success(`${decision === 'approve' ? 'Approved' : 'Denied'} ${okCount} run${okCount === 1 ? '' : 's'}`);
		}
	}

	function cancelBulk(): void {
		confirmingBulk = null;
		if (confirmTimer) clearTimeout(confirmTimer);
	}

	function openDrawer(runId: string): void {
		goto(`/approvals/${runId}`, { replaceState: false, keepFocus: true });
	}

	function closeDrawer(): void {
		goto('/approvals', { replaceState: false, keepFocus: true });
	}
</script>

<div class="flex h-full flex-col p-6">
	<header class="mb-4 flex items-baseline justify-between">
		<div>
			<h1 class="text-[20px] font-medium text-fg">Approvals</h1>
			<p class="mt-1 text-[13px] text-fg-muted">
				Runs awaiting human review before executing tool calls.
			</p>
		</div>
		<span class="font-mono text-[22px] text-fg tabular-nums">{approvals.count}</span>
	</header>

	{#if selection.size > 0}
		<div
			class="mb-3 flex items-center gap-2 rounded border border-edge bg-surface-1 px-3 py-2 text-[13px]"
		>
			<span class="font-mono text-[12px] text-fg-muted tabular-nums">
				{selection.size} selected
			</span>
			<Button
				variant="default"
				size="xs"
				onclick={() => startBulk('approve')}
			>
				{#if confirmingBulk === 'approve'}
					Confirm approve {selection.size}
				{:else}
					Approve {selection.size}
				{/if}
			</Button>
			<Button
				variant="ghost"
				size="xs"
				class="text-fg-muted hover:text-fail"
				onclick={() => startBulk('deny')}
			>
				{#if confirmingBulk === 'deny'}
					Confirm deny {selection.size}
				{:else}
					Deny {selection.size}
				{/if}
			</Button>
			{#if confirmingBulk}
				<Button variant="outline" size="xs" onclick={cancelBulk}>Cancel</Button>
			{/if}
			<span class="flex-1"></span>
			<Button
				variant="ghost"
				size="xs"
				onclick={() => {
					selection = new Set();
				}}
			>
				Clear
			</Button>
		</div>
	{/if}

	<ApprovalsQueue
		runs={approvals.runs}
		loading={!approvals.loaded}
		error={approvals.error}
		onOpen={openDrawer}
		onResolveOne={resolveOne}
		onRetry={approvals.refresh}
		bind:selection
		{submittingIds}
	/>
</div>

{#if drawerRunId}
	<ApprovalDrawer runId={drawerRunId} onClose={closeDrawer} />
{/if}

<style>
	.hover\:text-fail:hover {
		color: var(--color-fail);
	}
</style>
