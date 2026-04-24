<script lang="ts">
	import { Inbox, AlertTriangle, RefreshCw } from 'lucide-svelte';
	import { Button } from '$lib/components/ui/button';
	import { Skeleton } from '$lib/components/ui/skeleton';
	import type { PendingRun } from '$lib/api/approvals';
	import { previewOf } from './preview';

	let {
		runs,
		loading,
		error,
		onOpen,
		onResolveOne,
		onRetry,
		selection = $bindable(new Set<string>()),
		submittingIds = new Set<string>()
	}: {
		runs: PendingRun[];
		loading: boolean;
		error: string | null;
		onOpen: (runId: string) => void;
		onResolveOne: (run: PendingRun, decision: boolean) => void;
		onRetry: () => void;
		selection?: Set<string>;
		submittingIds?: Set<string>;
	} = $props();

	let focusIdx = $state(0);

	function ageString(createdAt: string): string {
		try {
			const then = new Date(createdAt).getTime();
			const now = Date.now();
			const secs = Math.max(0, Math.floor((now - then) / 1000));
			if (secs < 60) return `${secs}s`;
			const mins = Math.floor(secs / 60);
			if (mins < 60) return `${mins}m`;
			const hrs = Math.floor(mins / 60);
			if (hrs < 24) return `${hrs}h`;
			const days = Math.floor(hrs / 24);
			return `${days}d`;
		} catch {
			return '—';
		}
	}

	function runPreview(run: PendingRun): string {
		if (run.calls.length === 0) return '(no calls)';
		const first = previewOf(run.calls[0].tool_name, run.calls[0].arguments);
		if (run.calls.length === 1) return first;
		return `${first} + ${run.calls.length - 1} more`;
	}

	function toggleSelect(runId: string, run: PendingRun): void {
		if (run.calls.length !== 1) return; // bulk acts on single-call runs only
		const next = new Set(selection);
		if (next.has(runId)) next.delete(runId);
		else next.add(runId);
		selection = next;
	}

	function onKey(ev: KeyboardEvent): void {
		const target = ev.target as HTMLElement | null;
		if (target && ['INPUT', 'TEXTAREA'].includes(target.tagName)) return;
		if (runs.length === 0) return;

		if (ev.key === 'j') {
			focusIdx = Math.min(runs.length - 1, focusIdx + 1);
			ev.preventDefault();
		} else if (ev.key === 'k') {
			focusIdx = Math.max(0, focusIdx - 1);
			ev.preventDefault();
		} else if (ev.key === 'x') {
			const run = runs[focusIdx];
			if (run) toggleSelect(run.run_id, run);
			ev.preventDefault();
		} else if (ev.key === 'Enter') {
			const run = runs[focusIdx];
			if (run) onOpen(run.run_id);
			ev.preventDefault();
		} else if ((ev.key === 'a' || ev.key === 'A') && !ev.shiftKey && !ev.metaKey && !ev.ctrlKey) {
			const run = runs[focusIdx];
			if (run && run.calls.length === 1) onResolveOne(run, true);
			ev.preventDefault();
		} else if ((ev.key === 'd' || ev.key === 'D') && !ev.shiftKey && !ev.metaKey && !ev.ctrlKey) {
			const run = runs[focusIdx];
			if (run && run.calls.length === 1) onResolveOne(run, false);
			ev.preventDefault();
		}
	}
</script>

<svelte:window on:keydown={onKey} />

{#if error}
	<div
		class="mb-3 flex items-center gap-2 rounded border border-edge bg-surface-1 px-3 py-2 text-[13px] text-fg-muted"
	>
		<AlertTriangle size={14} style="color: var(--color-warn)" strokeWidth={1.75} />
		<span class="flex-1">Failed to load approvals. {error}</span>
		<Button variant="outline" size="xs" onclick={onRetry}>
			<RefreshCw size={12} /> Retry
		</Button>
	</div>
{/if}

{#if loading && runs.length === 0}
	<div class="flex flex-col gap-1">
		{#each [0.7, 0.85, 0.65, 0.9] as w, i (i)}
			<div class="h-11 overflow-hidden rounded border border-edge-subtle bg-surface-1 px-3 py-2">
				<Skeleton class="h-3" style="width: {w * 100}%" />
			</div>
		{/each}
	</div>
{:else if runs.length === 0}
	<div class="flex flex-col items-center justify-center py-16 text-center">
		<Inbox size={48} style="color: var(--color-fg-faint)" strokeWidth={1.25} />
		<p class="mt-6 text-[13px] text-fg-muted">
			No pending approvals — runs that request risky tool calls appear here.
		</p>
		<a
			href="/docs/security/approvals.md"
			class="mt-2 text-[12px] text-fg-faint underline-offset-4 hover:text-fg-muted hover:underline"
		>
			About approval gating →
		</a>
	</div>
{:else}
	<ul class="flex flex-col divide-y divide-edge-subtle overflow-hidden rounded border border-edge">
		{#each runs as run, i (run.run_id)}
			{@const isFocused = i === focusIdx}
			{@const multi = run.calls.length > 1}
			{@const selected = selection.has(run.run_id)}
			{@const busy = submittingIds.has(run.run_id)}
			<li
				class="group flex h-11 items-center gap-2 border-l-2 px-3 text-[13px] transition-colors
					{isFocused ? 'border-l-accent-primary bg-surface-2' : 'border-l-transparent hover:border-l-edge hover:bg-surface-1'}"
				aria-current={isFocused ? 'true' : undefined}
			>
				<label
					class="flex items-center"
					title={multi ? 'Bulk acts on single-call runs only' : undefined}
				>
					<input
						type="checkbox"
						checked={selected}
						disabled={multi || busy}
						onchange={() => toggleSelect(run.run_id, run)}
						aria-label={multi ? `Bulk unavailable for ${run.run_id}` : `Select ${run.run_id}`}
					/>
				</label>
				<!-- svelte-ignore a11y_click_events_have_key_events -->
				<!-- svelte-ignore a11y_no_static_element_interactions -->
				<div
					class="flex min-w-0 flex-1 cursor-pointer items-center gap-2"
					onclick={() => onOpen(run.run_id)}
				>
					<span class="min-w-0 truncate text-fg">{run.agent_name}</span>
					{#if multi}
						<span
							class="rounded bg-surface-2 px-1.5 py-0.5 font-mono text-[10px] text-fg-muted tabular-nums"
						>
							{run.calls.length}
						</span>
					{/if}
					<span class="min-w-0 flex-1 truncate font-mono text-[12px] text-fg-muted">
						{runPreview(run)}
					</span>
					<span class="shrink-0 font-mono text-[11px] text-fg-faint tabular-nums">
						{ageString(run.created_at)}
					</span>
				</div>
				<div class="flex shrink-0 items-center gap-1">
					{#if multi}
						<Button variant="outline" size="xs" onclick={() => onOpen(run.run_id)} disabled={busy}>
							Review {run.calls.length}
						</Button>
					{:else}
						<Button
							variant="default"
							size="xs"
							onclick={() => onResolveOne(run, true)}
							disabled={busy}
						>
							Approve
						</Button>
						<Button
							variant="ghost"
							size="xs"
							class="text-fg-muted hover:text-fail"
							onclick={() => onResolveOne(run, false)}
							disabled={busy}
						>
							Deny
						</Button>
					{/if}
				</div>
			</li>
		{/each}
	</ul>
{/if}

<style>
	.border-l-accent-primary {
		border-left-color: var(--color-accent-primary);
	}
	.hover\:text-fail:hover {
		color: var(--color-fail);
	}
</style>
