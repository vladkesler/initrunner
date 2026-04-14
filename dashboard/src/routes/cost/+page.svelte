<script lang="ts">
	import { onMount } from 'svelte';
	import { fetchCostSummary, fetchCostByAgent, fetchCostDaily, fetchCostByModel, fetchCostByTool } from '$lib/api/cost';
	import { listAgents } from '$lib/api/agents';
	import type { CostSummary, AgentCost, DailyCost, ModelCost, ToolCost, AgentSummary } from '$lib/api/types';
	import { Skeleton } from '$lib/components/ui/skeleton';
	import SpendChart from '$lib/components/cost/SpendChart.svelte';
	import AgentCostTable from '$lib/components/cost/AgentCostTable.svelte';
	import ModelCostTable from '$lib/components/cost/ModelCostTable.svelte';
	import ToolCostTable from '$lib/components/cost/ToolCostTable.svelte';
	import { formatCost } from '$lib/utils/format';
	import { toast } from '$lib/stores/toast.svelte';
	import { setCrumbs } from '$lib/stores/breadcrumb.svelte';

	type Period = '7d' | '30d' | '90d';
	const PERIOD_DAYS: Record<Period, number> = { '7d': 7, '30d': 30, '90d': 90 };

	let summary = $state<CostSummary | null>(null);
	let agents = $state<AgentSummary[]>([]);
	let dailyData = $state<DailyCost[]>([]);
	let agentData = $state<AgentCost[]>([]);
	let modelData = $state<ModelCost[]>([]);
	let toolData = $state<ToolCost[]>([]);
	let loading = $state(true);
	let rangeLoading = $state(false);
	let period = $state<Period>('30d');

	function sinceForPeriod(p: Period): string {
		const d = new Date();
		d.setUTCDate(d.getUTCDate() - PERIOD_DAYS[p]);
		return d.toISOString();
	}

	$effect(() => {
		setCrumbs([{ label: 'Cost' }]);
	});

	async function loadRange(p: Period) {
		rangeLoading = true;
		const since = sinceForPeriod(p);
		try {
			const [daily, byAgent, byModel, byTool] = await Promise.all([
				fetchCostDaily({ days: PERIOD_DAYS[p] }),
				fetchCostByAgent({ since }),
				fetchCostByModel({ since }),
				fetchCostByTool({ since }),
			]);
			dailyData = daily;
			agentData = byAgent;
			modelData = byModel;
			toolData = byTool;
		} catch {
			toast.error('Failed to load cost data');
		} finally {
			rangeLoading = false;
		}
	}

	async function setPeriod(p: Period) {
		period = p;
		await loadRange(p);
	}

	onMount(async () => {
		try {
			const since = sinceForPeriod(period);
			const [s, a, daily, byAgent, byModel, byTool] = await Promise.all([
				fetchCostSummary(),
				listAgents().catch(() => [] as AgentSummary[]),
				fetchCostDaily({ days: PERIOD_DAYS[period] }),
				fetchCostByAgent({ since }),
				fetchCostByModel({ since }),
				fetchCostByTool({ since }),
			]);
			summary = s;
			agents = a;
			dailyData = daily;
			agentData = byAgent;
			modelData = byModel;
			toolData = byTool;
		} catch {
			toast.error('Failed to connect to API server');
		} finally {
			loading = false;
		}
	});
</script>

<div class="space-y-5">
	{#if loading}
		<Skeleton class="h-6 w-32 bg-surface-1" />
		<Skeleton class="h-20 bg-surface-1" />
		<Skeleton class="h-52 bg-surface-1" />
		<Skeleton class="h-64 bg-surface-1" />
	{:else}
		<!-- Header + period tabs -->
		<div class="flex flex-wrap items-center justify-between gap-3">
			<h1 class="text-2xl font-semibold tracking-[-0.03em] text-fg">Cost</h1>

			<div class="flex items-center gap-0.5">
				{#each (['7d', '30d', '90d'] as const) as p}
					<button
						class="border-b-2 px-3 py-1.5 text-[13px] font-medium transition-[color,border-color] duration-150
							{period === p ? 'border-accent-primary-dim text-fg' : 'border-transparent text-fg-faint hover:text-fg-muted'}"
						onclick={() => setPeriod(p)}
					>
						{p}
					</button>
				{/each}
			</div>
		</div>

		<!-- Summary strip (fixed, not affected by period) -->
		{#if summary}
			<div class="flex border border-edge bg-surface-1 animate-fade-in-up">
				<div class="flex-1 px-4 py-3">
					<div class="metric-label">Today</div>
					<div class="metric-value mt-0.5" style="font-size: 18px">
						{formatCost(summary.today)}
					</div>
				</div>
				<div class="flex-1 border-l border-edge-subtle px-4 py-3">
					<div class="metric-label">This week</div>
					<div class="metric-value mt-0.5" style="font-size: 18px">
						{formatCost(summary.this_week)}
					</div>
				</div>
				<div class="flex-1 border-l border-edge-subtle px-4 py-3">
					<div class="metric-label">This month</div>
					<div class="metric-value mt-0.5" style="font-size: 18px">
						{formatCost(summary.this_month)}
					</div>
				</div>
				<div class="flex-1 border-l border-edge-subtle px-4 py-3">
					<div class="metric-label">All time</div>
					<div class="metric-value mt-0.5" style="font-size: 18px">
						{formatCost(summary.all_time)}
					</div>
				</div>
			</div>
		{/if}

		<!-- Spend chart -->
		<div class:opacity-50={rangeLoading} class="transition-opacity duration-150">
			<SpendChart data={dailyData} />
		</div>

		<!-- Agent + Model tables -->
		<div class="grid grid-cols-1 gap-5 lg:grid-cols-2" class:opacity-50={rangeLoading}>
			<div>
				<h2 class="section-label mb-3">By Agent</h2>
				<div class="border border-edge">
					<AgentCostTable data={agentData} {agents} />
				</div>
			</div>
			<div>
				<h2 class="section-label mb-3">By Model</h2>
				<div class="border border-edge">
					<ModelCostTable data={modelData} />
				</div>
			</div>
		</div>

		<!-- Tool table (full width) -->
		<div class:opacity-50={rangeLoading} class="transition-opacity duration-150">
			<h2 class="section-label mb-3">By Tool</h2>
			<div class="border border-edge">
				<ToolCostTable data={toolData} />
			</div>
		</div>
	{/if}
</div>
