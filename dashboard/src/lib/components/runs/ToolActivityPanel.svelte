<script lang="ts">
	import type { ToolEventData } from '$lib/api/types';

	let { events = [] }: { events?: ToolEventData[] } = $props();

	let containerEl: HTMLDivElement | undefined = $state();

	// Auto-scroll to bottom when events change
	$effect(() => {
		const _len = events.length;
		if (containerEl) {
			containerEl.scrollTop = containerEl.scrollHeight;
		}
	});

	function statusColor(status: string): string {
		if (status === 'running') return 'bg-accent-primary';
		if (status === 'ok') return 'bg-ok';
		return 'bg-fail';
	}

	function formatDuration(ms: number): string {
		if (ms < 1000) return `${ms}ms`;
		return `${(ms / 1000).toFixed(1)}s`;
	}
</script>

<div class="flex h-full max-h-[calc(100dvh-20rem)] flex-col border border-edge bg-surface-1">
	<div class="border-b border-edge px-3 py-2">
		<span class="section-label">Tool Activity</span>
	</div>

	<div
		bind:this={containerEl}
		class="flex-1 overflow-y-auto"
	>
		{#if events.length === 0}
			<div class="flex h-full min-h-[120px] items-center justify-center">
				<span class="text-[12px] text-fg-faint">No tool calls yet</span>
			</div>
		{:else}
			<div class="flex flex-col">
				{#each events as event, i (i)}
					<div class="flex items-start gap-2.5 border-b border-edge-subtle px-3 py-2">
						<span class="status-dot mt-1.5 {statusColor(event.status)}"></span>
						<div class="min-w-0 flex-1">
							<div class="flex items-baseline justify-between gap-2">
								<span class="truncate font-mono text-[12px] text-fg">{#if event.agent_name}<span class="text-fg-muted">{event.agent_name}</span>{' \u203A '}{/if}{event.tool_name}</span>
								{#if event.phase === 'complete'}
									<span class="shrink-0 font-mono text-[11px] text-fg-faint" style="font-variant-numeric: tabular-nums">
										{formatDuration(event.duration_ms)}
									</span>
								{:else}
									<span class="shrink-0 font-mono text-[11px] text-accent-primary">running</span>
								{/if}
							</div>
							{#if event.error_summary}
								<p class="mt-0.5 truncate text-[11px] text-fail">{event.error_summary}</p>
							{/if}
						</div>
					</div>
				{/each}
			</div>
		{/if}
	</div>
</div>
