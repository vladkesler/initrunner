<script lang="ts">
	import type { CostData, CostUpdateData, UsageData } from '$lib/api/types';
	import { formatCost } from '$lib/utils/format';

	interface ResultMetrics {
		tokens_in: number;
		tokens_out: number;
		total_tokens: number;
		cost?: CostData | null;
	}

	let {
		usage = null,
		result = null,
		running = false,
		costUpdate = null
	}: {
		usage?: UsageData | null;
		result?: ResultMetrics | null;
		running?: boolean;
		costUpdate?: CostUpdateData | null;
	} = $props();

	const hasResult = $derived(result !== null && result !== undefined);
	const hasBudget = $derived(
		usage?.budget?.max_tokens != null || usage?.budget?.total_limit != null
	);
	const budgetMax = $derived(
		usage?.budget?.total_limit ?? usage?.budget?.max_tokens ?? null
	);
	const budgetPercent = $derived.by(() => {
		if (!budgetMax || !hasResult) return null;
		return Math.min(100, Math.round((result!.total_tokens / budgetMax) * 100));
	});

</script>

<div class="border-t border-edge bg-surface-1 px-3 py-2">
	{#if hasResult}
		<!-- Final values -->
		<div class="flex items-center gap-3">
			<span class="font-mono text-[12px] text-fg" style="font-variant-numeric: tabular-nums">
				{result!.tokens_in.toLocaleString()} in / {result!.tokens_out.toLocaleString()} out
			</span>
			{#if result!.cost}
				<span class="font-mono text-[12px] text-fg-muted" style="font-variant-numeric: tabular-nums">
					{formatCost(result!.cost.total_cost_usd)}
				</span>
			{/if}
		</div>
		{#if hasBudget && budgetPercent !== null}
			<div class="mt-1.5 flex items-center gap-2">
				<div class="h-1 flex-1 bg-surface-3">
					<div
						class="h-full bg-accent-primary transition-[width] duration-300"
						style="width: {budgetPercent}%"
					></div>
				</div>
				<span class="font-mono text-[11px] text-fg-faint" style="font-variant-numeric: tabular-nums">
					{budgetPercent}%
				</span>
			</div>
		{/if}
	{:else if running}
		<!-- Streaming state with live cost estimate -->
		<div class="flex items-center gap-2">
			<div class="h-0.5 w-4 bg-accent-primary"></div>
			{#if costUpdate}
				<span class="font-mono text-[12px] text-fg-faint" style="font-variant-numeric: tabular-nums">
					~{costUpdate.estimated_tokens_out.toLocaleString()} tokens out
				</span>
				{#if costUpdate.estimated_output_cost_usd != null}
					<span class="font-mono text-[12px] text-fg-faint" style="font-variant-numeric: tabular-nums">
						~{formatCost(costUpdate.estimated_output_cost_usd)}
					</span>
				{/if}
			{:else}
				<span class="text-[12px] text-fg-faint">streaming...</span>
			{/if}
			{#if usage?.model}
				<span class="ml-auto font-mono text-[11px] text-fg-faint">{usage.model}</span>
			{/if}
		</div>
	{:else if usage}
		<!-- Pre-run: show budget frame -->
		<div class="flex items-center gap-2 text-[12px] text-fg-faint">
			{#if usage.model}
				<span class="font-mono">{usage.model}</span>
			{/if}
			{#if budgetMax}
				<span class="font-mono" style="font-variant-numeric: tabular-nums">
					budget: {budgetMax.toLocaleString()} tokens
				</span>
			{/if}
		</div>
	{/if}
</div>
