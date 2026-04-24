<script lang="ts">
	import { Check, X, ChevronDown, ChevronRight } from 'lucide-svelte';
	import { Button } from '$lib/components/ui/button';
	import type { PendingCall } from '$lib/api/types';
	import { previewOf } from './preview';
	import Kbd from './Kbd.svelte';

	type Decision = 'approve' | 'deny';

	let {
		runId,
		calls,
		submitting = false,
		onSubmit,
		compact = false
	}: {
		runId: string;
		calls: PendingCall[];
		submitting?: boolean;
		onSubmit: (decisions: Record<string, boolean>) => void;
		/** Compact mode drops header chrome — used inline in RunPanel where the
		 * surrounding run meta is already visible. */
		compact?: boolean;
	} = $props();

	let decisions = $state<Record<string, Decision | undefined>>({});
	let expanded = $state<Record<string, boolean>>({});
	let focusIdx = $state(0);

	const callsState = $derived(calls);
	const decided = $derived(
		callsState.filter((c) => decisions[c.tool_call_id] !== undefined).length
	);
	const ready = $derived(decided === callsState.length && callsState.length > 0);

	function toggleDecision(callId: string, decision: Decision): void {
		if (decisions[callId] === decision) {
			decisions = { ...decisions, [callId]: undefined };
		} else {
			decisions = { ...decisions, [callId]: decision };
		}
	}

	function decideAll(decision: Decision): void {
		const next: Record<string, Decision> = {};
		for (const c of callsState) next[c.tool_call_id] = decision;
		decisions = next;
	}

	function submit(): void {
		if (!ready || submitting) return;
		const payload: Record<string, boolean> = {};
		for (const c of callsState) {
			const d = decisions[c.tool_call_id];
			if (d === undefined) return;
			payload[c.tool_call_id] = d === 'approve';
		}
		onSubmit(payload);
	}

	function onKey(ev: KeyboardEvent): void {
		// Ignore if the user is typing in a field
		const target = ev.target as HTMLElement | null;
		if (target && ['INPUT', 'TEXTAREA'].includes(target.tagName)) return;

		if (ev.key === 'j') {
			focusIdx = Math.min(callsState.length - 1, focusIdx + 1);
			ev.preventDefault();
		} else if (ev.key === 'k') {
			focusIdx = Math.max(0, focusIdx - 1);
			ev.preventDefault();
		} else if (ev.key === 'A' && ev.shiftKey) {
			decideAll('approve');
			ev.preventDefault();
		} else if (ev.key === 'D' && ev.shiftKey) {
			decideAll('deny');
			ev.preventDefault();
		} else if ((ev.key === 'a' || ev.key === 'A') && !ev.shiftKey && !ev.metaKey && !ev.ctrlKey) {
			const call = callsState[focusIdx];
			if (call) toggleDecision(call.tool_call_id, 'approve');
			ev.preventDefault();
		} else if ((ev.key === 'd' || ev.key === 'D') && !ev.shiftKey && !ev.metaKey && !ev.ctrlKey) {
			const call = callsState[focusIdx];
			if (call) toggleDecision(call.tool_call_id, 'deny');
			ev.preventDefault();
		} else if (ev.key === 'Enter' && ready) {
			submit();
			ev.preventDefault();
		}
	}

	function stateBarClass(decision: Decision | undefined): string {
		if (decision === 'approve') return 'bg-accent-primary';
		if (decision === 'deny') return 'bg-fail';
		return 'bg-edge-subtle';
	}
</script>

<svelte:window on:keydown={onKey} />

<section
	class="rounded-lg border border-edge bg-surface-1"
	aria-label="Tool calls awaiting approval"
>
	{#if !compact}
		<header class="flex items-center justify-between border-b border-edge-subtle px-3 py-2">
			<div class="flex items-center gap-2 text-[13px] text-fg">
				<span class="section-label text-[10px] uppercase tracking-[0.15em] text-fg-faint">
					Awaiting approval
				</span>
				<span class="font-mono text-[12px] text-fg-muted tabular-nums">
					{callsState.length} call{callsState.length === 1 ? '' : 's'}
				</span>
			</div>
			<span class="font-mono text-[11px] text-fg-faint" title="Run id">
				run: {runId.slice(0, 8)}
			</span>
		</header>
	{/if}

	{#if callsState.length > 1}
		<div class="flex items-center gap-2 border-b border-edge-subtle px-3 py-2">
			<Button
				variant="default"
				size="xs"
				onclick={() => decideAll('approve')}
				disabled={submitting}
			>
				Approve all <Kbd>⇧A</Kbd>
			</Button>
			<Button
				variant="ghost"
				size="xs"
				onclick={() => decideAll('deny')}
				disabled={submitting}
			>
				Deny all <Kbd>⇧D</Kbd>
			</Button>
		</div>
	{/if}

	<ul class="divide-y divide-edge-subtle">
		{#each callsState as call, i (call.tool_call_id)}
			{@const decision = decisions[call.tool_call_id]}
			{@const isFocused = i === focusIdx}
			<li
				class="relative flex items-start gap-3 px-3 py-2.5 transition-colors
					{isFocused ? 'bg-surface-2' : 'hover:bg-surface-2/50'}"
				aria-current={isFocused ? 'true' : undefined}
			>
				<span class="absolute left-0 top-0 h-full w-0.5 {stateBarClass(decision)}" aria-hidden="true"
				></span>

				<div class="min-w-0 flex-1 pl-1">
					<div class="flex items-baseline gap-2">
						<span class="font-mono text-[11px] text-fg-faint">{i + 1}.</span>
						<span class="text-[13px] font-medium text-fg">{call.tool_name}</span>
					</div>
					<div class="mt-0.5 overflow-hidden font-mono text-[12px] text-fg-muted">
						{previewOf(call.tool_name, call.arguments)}
					</div>
					<button
						type="button"
						class="mt-1 inline-flex items-center gap-1 text-[11px] text-fg-faint hover:text-fg-muted"
						onclick={() =>
							(expanded = { ...expanded, [call.tool_call_id]: !expanded[call.tool_call_id] })}
					>
						{#if expanded[call.tool_call_id]}
							<ChevronDown size={12} strokeWidth={1.5} /> Hide full arguments
						{:else}
							<ChevronRight size={12} strokeWidth={1.5} /> Show full arguments
						{/if}
					</button>
					{#if expanded[call.tool_call_id]}
						<pre
							class="mt-1.5 overflow-x-auto rounded border border-edge-subtle bg-surface-0 p-2 font-mono text-[11px] leading-snug text-fg-muted"
						>{JSON.stringify(call.arguments, null, 2)}</pre>
					{/if}
				</div>

				<div class="flex shrink-0 items-center gap-1.5">
					{#if decision === 'approve'}
						<Button
							variant="default"
							size="icon-xs"
							aria-label="Approved — click to undo"
							onclick={() => toggleDecision(call.tool_call_id, 'approve')}
							disabled={submitting}
						>
							<Check size={12} />
						</Button>
					{:else if decision === 'deny'}
						<Button
							variant="destructive"
							size="icon-xs"
							aria-label="Denied — click to undo"
							onclick={() => toggleDecision(call.tool_call_id, 'deny')}
							disabled={submitting}
						>
							<X size={12} />
						</Button>
					{:else}
						<Button
							variant="default"
							size="xs"
							onclick={() => toggleDecision(call.tool_call_id, 'approve')}
							disabled={submitting}
						>
							Approve <Kbd>A</Kbd>
						</Button>
						<Button
							variant="ghost"
							size="xs"
							class="text-fg-muted hover:text-fail hover:border-fail/40"
							onclick={() => toggleDecision(call.tool_call_id, 'deny')}
							disabled={submitting}
						>
							Deny <Kbd>D</Kbd>
						</Button>
					{/if}
				</div>
			</li>
		{/each}
	</ul>

	<footer class="flex items-center justify-between border-t border-edge-subtle px-3 py-2.5">
		<span class="font-mono text-[11px] text-fg-faint tabular-nums">
			{decided} of {callsState.length} set
		</span>
		<Button
			variant="default"
			size="sm"
			onclick={submit}
			disabled={!ready || submitting}
		>
			{#if submitting}
				Submitting…
			{:else}
				Submit decisions <Kbd>↵</Kbd>
			{/if}
		</Button>
	</footer>
</section>

<style>
	.bg-accent-primary {
		background: var(--color-accent-primary);
	}
	.bg-fail {
		background: var(--color-fail);
	}
	.bg-edge-subtle {
		background: var(--color-edge-subtle, #1e1e22);
	}
	.hover\:text-fail:hover {
		color: var(--color-fail);
	}
	.hover\:border-fail\/40:hover {
		border-color: color-mix(in oklch, var(--color-fail) 40%, transparent);
	}
</style>
