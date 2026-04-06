<script lang="ts">
	import type { AgentCost, AgentSummary } from '$lib/api/types';
	import { formatCost } from '$lib/utils/format';
	import { ChevronUp, ChevronDown } from 'lucide-svelte';

	let {
		data,
		agents = []
	}: {
		data: AgentCost[];
		agents?: AgentSummary[];
	} = $props();

	type SortKey = 'agent_name' | 'run_count' | 'tokens_in' | 'tokens_out' | 'avg_cost_per_run' | 'total_cost_usd';
	let sortKey = $state<SortKey>('total_cost_usd');
	let sortAsc = $state(false);

	const sorted = $derived.by(() => {
		const copy = [...data];
		copy.sort((a, b) => {
			const av = a[sortKey];
			const bv = b[sortKey];
			if (av === null && bv === null) return 0;
			if (av === null) return 1;
			if (bv === null) return -1;
			if (typeof av === 'string') return sortAsc ? av.localeCompare(bv as string) : (bv as string).localeCompare(av);
			return sortAsc ? (av as number) - (bv as number) : (bv as number) - (av as number);
		});
		return copy;
	});

	function toggleSort(key: SortKey) {
		if (sortKey === key) {
			sortAsc = !sortAsc;
		} else {
			sortKey = key;
			sortAsc = key === 'agent_name';
		}
	}

	const agentIdMap = $derived.by(() => {
		const counts = new Map<string, number>();
		const idMap = new Map<string, string>();
		for (const a of agents) {
			counts.set(a.name, (counts.get(a.name) ?? 0) + 1);
			idMap.set(a.name, a.id);
		}
		const unique = new Map<string, string>();
		for (const [name, count] of counts) {
			if (count === 1) unique.set(name, idMap.get(name)!);
		}
		return unique;
	});

	function formatTokens(n: number): string {
		if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
		if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
		return `${n}`;
	}
</script>

{#snippet sortIcon(key: SortKey)}
	{#if sortKey === key}
		{#if sortAsc}
			<ChevronUp size={10} class="inline-block" />
		{:else}
			<ChevronDown size={10} class="inline-block" />
		{/if}
	{/if}
{/snippet}

{#if data.length === 0}
	<div class="flex items-center justify-center py-12 text-[13px] text-fg-faint">
		No agent cost data
	</div>
{:else}
	<div class="max-h-[480px] overflow-y-auto">
		<table class="w-full">
			<thead class="sticky top-0 z-10">
				<tr class="border-b border-edge bg-surface-05">
					<th class="section-label cursor-pointer px-3 py-2 text-left" onclick={() => toggleSort('agent_name')}>Agent {@render sortIcon('agent_name')}</th>
					<th class="section-label w-16 cursor-pointer px-3 py-2 text-right" onclick={() => toggleSort('run_count')}>Runs {@render sortIcon('run_count')}</th>
					<th class="section-label hidden w-20 cursor-pointer px-3 py-2 text-right lg:table-cell" onclick={() => toggleSort('tokens_in')}>Tk In {@render sortIcon('tokens_in')}</th>
					<th class="section-label hidden w-20 cursor-pointer px-3 py-2 text-right lg:table-cell" onclick={() => toggleSort('tokens_out')}>Tk Out {@render sortIcon('tokens_out')}</th>
					<th class="section-label w-20 cursor-pointer px-3 py-2 text-right" onclick={() => toggleSort('avg_cost_per_run')}>Avg/Run {@render sortIcon('avg_cost_per_run')}</th>
					<th class="section-label w-24 cursor-pointer px-3 py-2 text-right" onclick={() => toggleSort('total_cost_usd')}>Total {@render sortIcon('total_cost_usd')}</th>
				</tr>
			</thead>
			<tbody>
				{#each sorted as entry (entry.agent_name)}
					{@const agentId = agentIdMap.get(entry.agent_name)}
					{@const isClickable = !!agentId}
					<tr
						class="border-b border-edge-subtle transition-[background-color] duration-150 hover:bg-surface-1"
						class:cursor-pointer={isClickable}
						onclick={() => isClickable && window.location.assign(`/agents/${agentId}`)}
						role={isClickable ? 'button' : undefined}
						tabindex={isClickable ? 0 : undefined}
						onkeydown={(e) => isClickable && e.key === 'Enter' && window.location.assign(`/agents/${agentId}`)}
					>
						<td class="px-3 py-2 font-mono text-[13px] text-fg-muted">{entry.agent_name}</td>
						<td class="w-16 px-3 py-2 text-right font-mono text-[13px] text-fg-faint" style="font-variant-numeric: tabular-nums">
							{entry.run_count}
						</td>
						<td class="hidden w-20 px-3 py-2 text-right font-mono text-[13px] text-fg-faint lg:table-cell" style="font-variant-numeric: tabular-nums">
							{formatTokens(entry.tokens_in)}
						</td>
						<td class="hidden w-20 px-3 py-2 text-right font-mono text-[13px] text-fg-faint lg:table-cell" style="font-variant-numeric: tabular-nums">
							{formatTokens(entry.tokens_out)}
						</td>
						<td class="w-20 px-3 py-2 text-right font-mono text-[13px] text-fg-faint" style="font-variant-numeric: tabular-nums">
							{formatCost(entry.avg_cost_per_run)}
						</td>
						<td class="w-24 px-3 py-2 text-right font-mono text-[13px]" style="font-variant-numeric: tabular-nums">
							{#if entry.total_cost_usd !== null && entry.total_cost_usd > 0}
								<span class="text-accent-primary">{formatCost(entry.total_cost_usd)}</span>
							{:else}
								<span class="text-fg-faint">{formatCost(entry.total_cost_usd)}</span>
							{/if}
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>
{/if}
