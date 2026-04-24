<script lang="ts">
	import { onMount } from 'svelte';
	import { X } from 'lucide-svelte';
	import { Skeleton } from '$lib/components/ui/skeleton';
	import { getPendingRun, type PendingRun } from '$lib/api/approvals';
	import { approvals } from '$lib/stores/approvals.svelte';
	import { toast } from '$lib/stores/toast.svelte';
	import ApprovalCardGroup from './ApprovalCardGroup.svelte';

	let { runId, onClose }: { runId: string; onClose: () => void } = $props();

	let run = $state<PendingRun | null>(null);
	let loading = $state(true);
	let loadError = $state<string | null>(null);
	let submitting = $state(false);
	let resumed = $state<string | null>(null);

	async function load(): Promise<void> {
		loading = true;
		loadError = null;
		try {
			run = await getPendingRun(runId);
		} catch (e) {
			if (e && typeof e === 'object' && 'status' in e && e.status === 404) {
				toast.info('Already resolved.');
				onClose();
				return;
			}
			loadError = e instanceof Error ? e.message : String(e);
		} finally {
			loading = false;
		}
	}

	onMount(() => {
		void load();
	});

	async function submit(decisions: Record<string, boolean>): Promise<void> {
		submitting = true;
		try {
			const resp = await approvals.submit(runId, decisions);
			if (resp.status === 'paused') {
				toast.info(`Run paused again with ${resp.pending_approvals.length} new call(s)`);
				await load();
			} else {
				resumed = resp.output || 'Resumed.';
				setTimeout(onClose, 2500);
			}
		} catch (e) {
			if (e && typeof e === 'object' && 'status' in e && e.status === 404) {
				onClose();
				return;
			}
			toast.error(e instanceof Error ? e.message : String(e));
		} finally {
			submitting = false;
		}
	}

	function onKey(e: KeyboardEvent): void {
		if (e.key === 'Escape') onClose();
	}

	function formatTimestamp(ts: string): string {
		try {
			return new Date(ts).toLocaleString();
		} catch {
			return ts;
		}
	}
</script>

<svelte:window on:keydown={onKey} />

<!-- Backdrop -->
<!-- svelte-ignore a11y_no_static_element_interactions -->
<div
	class="fixed inset-0 z-40 bg-black/40"
	onclick={onClose}
	onkeydown={(e) => e.key === 'Escape' && onClose()}
></div>

<!-- Drawer -->
<div
	class="fixed inset-y-0 right-0 z-50 flex w-full max-w-xl flex-col border-l border-edge bg-surface-0 shadow-2xl"
	role="dialog"
	aria-labelledby="approval-drawer-title"
>
	<header class="flex items-center justify-between border-b border-edge-subtle px-4 py-3">
		<div class="min-w-0">
			<h2 id="approval-drawer-title" class="text-[15px] font-medium text-fg">
				{run ? `${run.agent_name} · ${run.calls.length} call${run.calls.length === 1 ? '' : 's'} awaiting` : 'Loading…'}
			</h2>
			<p class="mt-0.5 font-mono text-[11px] text-fg-faint">run_id: {runId}</p>
		</div>
		<button
			type="button"
			class="rounded p-1 text-fg-faint transition-colors hover:bg-surface-2 hover:text-fg-muted"
			aria-label="Close"
			onclick={onClose}
		>
			<X size={16} />
		</button>
	</header>

	<div class="flex-1 overflow-y-auto p-4">
		{#if loading}
			<div class="flex flex-col gap-2">
				<Skeleton class="h-4 w-1/2" />
				<Skeleton class="h-20 w-full" />
				<Skeleton class="h-20 w-full" />
			</div>
		{:else if loadError}
			<p class="text-[13px] text-fail">{loadError}</p>
		{:else if run}
			<dl class="mb-4 grid grid-cols-[80px_1fr] gap-y-1 text-[12px]">
				<dt class="text-fg-faint">agent</dt>
				<dd class="text-fg-muted">{run.agent_name}</dd>
				<dt class="text-fg-faint">created</dt>
				<dd class="font-mono text-fg-muted">{formatTimestamp(run.created_at)}</dd>
				{#if run.role_path}
					<dt class="text-fg-faint">role</dt>
					<dd class="truncate font-mono text-fg-muted" title={run.role_path}>
						{run.role_path}
					</dd>
				{/if}
			</dl>

			{#if run.originating_prompt}
				<div class="mb-4">
					<div class="mb-1 text-[10px] uppercase tracking-[0.15em] text-fg-faint">
						Originating prompt
					</div>
					<blockquote
						class="border-l-2 border-edge-subtle pl-3 text-[13px] italic text-fg-muted"
					>
						{run.originating_prompt}
					</blockquote>
				</div>
			{/if}

			{#if resumed}
				<div class="mb-3 rounded border border-accent-primary/40 bg-surface-1 px-3 py-2 text-[13px] text-fg">
					{resumed}
				</div>
			{/if}

			<ApprovalCardGroup
				runId={run.run_id}
				calls={run.calls}
				{submitting}
				onSubmit={submit}
				compact
			/>
		{/if}
	</div>
</div>

<style>
	.text-fail {
		color: var(--color-fail);
	}
	.border-accent-primary\/40 {
		border-color: color-mix(in oklch, var(--color-accent-primary) 40%, transparent);
	}
</style>
