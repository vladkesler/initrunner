<script lang="ts">
	import type { TriggerStat } from '$lib/api/types';
	import { ChevronRight } from 'lucide-svelte';

	let { stats }: { stats: TriggerStat[] } = $props();

	function timeAgo(iso: string): string {
		const diffMs = Date.now() - new Date(iso).getTime();
		if (diffMs < 0) return 'just now';
		const seconds = Math.floor(diffMs / 1000);
		if (seconds < 60) return `${seconds}s ago`;
		const minutes = Math.floor(seconds / 60);
		if (minutes < 60) return `${minutes}m ago`;
		const hours = Math.floor(minutes / 60);
		if (hours < 24) return `${hours}h ago`;
		const days = Math.floor(hours / 24);
		return `${days}d ago`;
	}

	function timeUntil(iso: string): string {
		const diffMs = new Date(iso).getTime() - Date.now();
		if (diffMs <= 0) return 'now';
		const seconds = Math.floor(diffMs / 1000);
		if (seconds < 60) return `in ${seconds}s`;
		const minutes = Math.floor(seconds / 60);
		if (minutes < 60) return `in ${minutes}m`;
		const hours = Math.floor(minutes / 60);
		if (hours < 24) return `in ${hours}h`;
		const days = Math.floor(hours / 24);
		return `in ${days}d`;
	}

	function successRate(s: TriggerStat): number {
		if (s.fire_count === 0) return 0;
		return Math.round((s.success_count / s.fire_count) * 100);
	}

	function rateColor(rate: number): string {
		if (rate >= 90) return 'text-ok';
		if (rate >= 70) return 'text-warn';
		return 'text-fail';
	}

	let expandedErrors: Record<number, boolean> = $state({});
</script>

<div>
	<h3
		class="mb-2 font-mono text-[12px] font-medium uppercase tracking-[0.1em] text-fg-faint"
	>
		Triggers
	</h3>
	<div class="grid gap-2">
		{#each stats as stat, i}
			<div
				class="card-surface bg-surface-1 px-4 py-3 animate-fade-in-up"
				style="animation-delay: {i * 60}ms"
			>
				<!-- Type + summary -->
				<div class="font-mono text-[13px]">
					<span class="text-accent-secondary">{stat.trigger_type}</span>
					<span class="ml-1.5 text-fg-muted">{stat.summary}</span>
				</div>

				<!-- Stats row -->
				{#if stat.fire_count > 0}
					<div
						class="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 font-mono text-[13px]"
						style="font-variant-numeric: tabular-nums"
					>
						<span>
							<span class="text-fg-faint">fires</span>
							<span class="ml-1 text-fg-muted">{stat.fire_count.toLocaleString()}</span>
						</span>
						<span>
							<span class="text-fg-faint">success</span>
							<span class="ml-1 {rateColor(successRate(stat))}"
								>{successRate(stat)}%</span
							>
						</span>
						<span>
							<span class="text-fg-faint">avg</span>
							<span class="ml-1 text-fg-muted"
								>{stat.avg_duration_ms.toLocaleString()}ms</span
							>
						</span>
						{#if stat.last_fire_time}
							<span>
								<span class="text-fg-faint">last</span>
								<span class="ml-1 text-fg-muted">{timeAgo(stat.last_fire_time)}</span>
							</span>
						{/if}
						{#if stat.next_check_time}
							<span>
								<span class="text-fg-faint">next</span>
								<span class="ml-1 text-accent-primary"
									>{timeUntil(stat.next_check_time)}</span
								>
							</span>
						{/if}
					</div>
				{:else}
					<div class="mt-1.5 flex gap-x-4 font-mono text-[13px]">
						<span class="text-fg-faint">no fires recorded</span>
						{#if stat.next_check_time}
							<span>
								<span class="text-fg-faint">next</span>
								<span class="ml-1 text-accent-primary"
									>{timeUntil(stat.next_check_time)}</span
								>
							</span>
						{/if}
					</div>
				{/if}

				<!-- Last error (collapsed) -->
				{#if stat.last_error}
					<div class="mt-1.5">
						<button
							class="flex items-center gap-1 font-mono text-[12px] text-fail/70 transition-[color] duration-150 hover:text-fail"
							onclick={() => (expandedErrors[i] = !expandedErrors[i])}
						>
							<ChevronRight
								size={10}
								class="shrink-0 transition-transform duration-150 {expandedErrors[i] ? 'rotate-90' : ''}"
							/>
							last error
						</button>
						{#if expandedErrors[i]}
							<pre
								class="mt-1 max-h-24 overflow-auto pl-[14px] font-mono text-[12px] leading-relaxed text-fail/80"
							>{stat.last_error}</pre>
						{/if}
					</div>
				{/if}
			</div>
		{/each}
	</div>
</div>
