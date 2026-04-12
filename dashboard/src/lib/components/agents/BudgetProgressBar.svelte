<script lang="ts">
	import { onMount } from 'svelte';
	import { fetchBudgetProgress } from '$lib/api/agents';
	import type { BudgetGauge, BudgetProgress } from '$lib/api/types';
	import { formatCost } from '$lib/utils/format';

	let { agentId }: { agentId: string } = $props();

	let progress: BudgetProgress | null = $state(null);
	let timer: ReturnType<typeof setInterval> | null = null;

	async function load() {
		try {
			progress = await fetchBudgetProgress(agentId);
		} catch {
			// best-effort
		}
	}

	onMount(() => {
		load();
		timer = setInterval(load, 30_000);
		return () => {
			if (timer) clearInterval(timer);
		};
	});

	const gauges = $derived.by(() => {
		if (!progress) return [];
		const entries: { label: string; gauge: BudgetGauge }[] = [];
		if (progress.daily_tokens) entries.push({ label: 'Daily tokens', gauge: progress.daily_tokens });
		if (progress.daily_cost) entries.push({ label: 'Daily cost', gauge: progress.daily_cost });
		if (progress.weekly_cost) entries.push({ label: 'Weekly cost', gauge: progress.weekly_cost });
		if (progress.lifetime_tokens) entries.push({ label: 'Lifetime tokens', gauge: progress.lifetime_tokens });
		return entries;
	});

	function barColor(level: string): string {
		if (level === 'exhausted' || level === 'warning_95') return 'bg-fail';
		if (level === 'warning_80') return 'bg-warn';
		return 'bg-ok';
	}

	function formatConsumed(label: string, gauge: BudgetGauge): string {
		if (label.includes('cost')) {
			return `${formatCost(gauge.consumed)} / ${formatCost(gauge.limit)}`;
		}
		return `${gauge.consumed.toLocaleString()} / ${gauge.limit.toLocaleString()}`;
	}
</script>

{#if gauges.length > 0}
	<div class="grid gap-2 {gauges.length > 2 ? 'grid-cols-2 lg:grid-cols-4' : `grid-cols-${gauges.length}`}">
		{#each gauges as { label, gauge }}
			<div class="card-surface bg-surface-1 px-3 py-2">
				<div class="flex items-center justify-between">
					<span class="text-[12px] text-fg-faint">{label}</span>
					<span
						class="font-mono text-[11px] text-fg-faint"
						style="font-variant-numeric: tabular-nums"
					>
						{gauge.percent}%
					</span>
				</div>
				<div class="mt-1.5 h-1 bg-surface-3">
					<div
						class="h-full transition-[width] duration-300 {barColor(gauge.warning_level)}"
						style="width: {gauge.percent}%"
					></div>
				</div>
				<div class="mt-1 font-mono text-[11px] text-fg-faint" style="font-variant-numeric: tabular-nums">
					{formatConsumed(label, gauge)}
				</div>
			</div>
		{/each}
	</div>
{/if}
