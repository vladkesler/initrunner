<script lang="ts">
	import { onMount } from 'svelte';
	import { listAgents, deleteAgent } from '$lib/api/agents';
	import type { AgentSummary } from '$lib/api/types';
	import AgentList from '$lib/components/agents/AgentList.svelte';
	import AgentFlowCanvas from '$lib/components/agents/AgentFlowCanvas.svelte';
	import QuickRunDrawer from '$lib/components/runs/QuickRunDrawer.svelte';
	import CapabilityFilterBar from '$lib/components/agents/CapabilityFilterBar.svelte';
	import ConfirmDeleteDialog from '$lib/components/ui/ConfirmDeleteDialog.svelte';
	import { Skeleton } from '$lib/components/ui/skeleton';
	import { Search, Workflow, List, X } from 'lucide-svelte';
	import { safeGet, safeSet } from '$lib/utils/storage';
	import { toast } from '$lib/stores/toast.svelte';
	import { setCrumbs } from '$lib/stores/breadcrumb.svelte';

	$effect(() => { setCrumbs([{ label: 'Agents' }]); });

	let agents = $state<AgentSummary[]>([]);
	let loading = $state(true);
	let query = $state('');
	let activeFilter = $state('all');
	let viewMode = $state<'flow' | 'list'>('flow');
	let searchEl: HTMLInputElement | undefined = $state();
	let isMobile = $state(false);
	let pendingDelete: AgentSummary | null = $state(null);
	let drawerAgent: { id: string; name: string } | null = $state(null);

	function openQuickRun(agent: AgentSummary) {
		drawerAgent = { id: agent.id, name: agent.name };
	}

	const isFiltering = $derived(activeFilter !== 'all' || query.trim().length > 0);

	// Compute which agent IDs should be dimmed (don't match filter)
	const dimmedIds = $derived.by(() => {
		if (!isFiltering) return new Set<string>();
		const ids = new Set<string>();
		for (const a of agents) {
			if (!matchesFilter(a)) ids.add(a.id);
		}
		return ids;
	});

	// Filtered list for list view
	const filtered = $derived(() => {
		if (!isFiltering) return agents;
		return agents.filter((a) => matchesFilter(a));
	});

	function matchesFilter(a: AgentSummary): boolean {
		if (activeFilter !== 'all') {
			const pass = (() => {
				switch (activeFilter) {
					case 'equipped': return a.features.includes('tools');
					case 'reactive': return a.features.includes('triggers');
					case 'intelligence': return a.features.includes('ingest') || a.features.includes('memory');
					case 'connected': return a.features.includes('sinks');
					case 'skilled': return a.features.includes('skills');
					case 'cognitive': return a.features.includes('reasoning') || a.features.includes('autonomy');
					case 'errored': return a.error !== null;
					default: return true;
				}
			})();
			if (!pass) return false;
		}
		if (query.trim()) {
			const q = query.toLowerCase();
			return a.name.toLowerCase().includes(q) ||
				a.description.toLowerCase().includes(q) ||
				a.tags.some((t) => t.toLowerCase().includes(q)) ||
				a.model.toLowerCase().includes(q) ||
				a.provider.toLowerCase().includes(q);
		}
		return true;
	}

	function clearFilters() {
		query = '';
		activeFilter = 'all';
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === '/' && !e.metaKey && !e.ctrlKey && document.activeElement?.tagName !== 'INPUT') {
			e.preventDefault();
			searchEl?.focus();
		}
	}

	onMount(() => {
		isMobile = window.innerWidth < 1024;
		const stored = safeGet('agents-view-mode');
		if (stored === 'list' || stored === 'flow') viewMode = stored;
		if (isMobile) viewMode = 'list';

		listAgents()
			.then((result) => (agents = result))
			.catch(() => { toast.error('Failed to load agents'); })
			.finally(() => (loading = false));
	});

	function setViewMode(mode: 'flow' | 'list') {
		viewMode = mode;
		safeSet('agents-view-mode', mode);
	}
</script>

<svelte:window onkeydown={handleKeydown} />

{#if viewMode === 'flow' && !loading}
	<!-- Flow view: toolbar + canvas -->
	<div class="-m-6 lg:-m-8 flex flex-col" style:height="100dvh">
		<!-- Toolbar -->
		<div class="flex flex-wrap items-center gap-3 border-b border-edge bg-surface-0 px-4 py-2.5">
			<div class="flex items-center gap-2.5">
				<h1 class="text-base font-semibold tracking-[-0.02em] text-fg">Agents</h1>
				<span class="border border-edge bg-surface-1 px-1.5 py-0.5 font-mono text-[11px] text-fg-faint">{agents.length}</span>
			</div>

			<!-- Search -->
			<div class="relative">
				<Search size={13} class="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-fg-faint" />
				<input
					bind:this={searchEl}
					bind:value={query}
					placeholder="Search..."
					class="w-48 border border-edge bg-surface-1 py-1 pl-8 pr-7 font-mono text-[12px] text-fg outline-none transition-[border-color,box-shadow] duration-150 placeholder:text-fg-faint focus:w-64 focus:border-accent-primary/40 focus:shadow-[0_0_0_3px_oklch(0.91_0.20_128/0.08)]"
				/>
				{#if query}
					<button class="absolute right-2 top-1/2 -translate-y-1/2 text-fg-faint hover:text-fg-muted" onclick={() => (query = '')}><X size={12} /></button>
				{:else}
					<kbd class="absolute right-2 top-1/2 -translate-y-1/2 rounded-full border border-edge bg-surface-2 px-1 py-0.5 font-mono text-[10px] text-fg-faint">/</kbd>
				{/if}
			</div>

			<!-- Filters -->
			<CapabilityFilterBar {agents} {activeFilter} onFilterChange={(f) => (activeFilter = f)} />

			{#if isFiltering}
				<div class="flex items-center gap-1.5 text-[11px] text-fg-faint">
					<span class="font-mono" style="font-variant-numeric: tabular-nums">{agents.length - dimmedIds.size}</span>
					<span>of {agents.length}</span>
					<button class="rounded-full border border-edge bg-surface-1 px-2 py-0.5 font-mono text-[10px] text-fg-faint hover:text-fg-muted" onclick={clearFilters}>Clear</button>
				</div>
			{/if}

			<!-- Spacer + view toggle -->
			<div class="ml-auto flex items-center gap-0.5 rounded-full border border-edge bg-surface-1 p-0.5">
				<button class="flex items-center justify-center rounded-full p-1.5 bg-surface-2 text-fg" aria-label="Flow view">
					<Workflow size={13} />
				</button>
				<button
					class="flex items-center justify-center rounded-full p-1.5 text-fg-faint transition-[color,background-color] duration-150"
					onclick={() => setViewMode('list')}
					aria-label="List view"
				>
					<List size={13} />
				</button>
			</div>
		</div>

		<!-- Canvas -->
		<div class="min-h-0 flex-1" style:width="100%">
			<AgentFlowCanvas {agents} {dimmedIds} onRun={openQuickRun} />
		</div>
	</div>
{:else}
	<!-- List view -->
	<div class="space-y-5">
		<div class="flex items-center justify-between">
			<div class="flex items-center gap-3">
				<h1 class="text-2xl font-semibold tracking-[-0.03em] text-fg">Agents</h1>
				{#if !loading}
					<span class="border border-edge bg-surface-1 px-2 py-0.5 font-mono text-[12px] text-fg-faint">{agents.length}</span>
				{/if}
			</div>
			{#if !isMobile}
				<div class="flex items-center gap-0.5 rounded-full border border-edge bg-surface-1 p-0.5">
					<button
						class="flex items-center justify-center rounded-full p-1.5 text-fg-faint transition-[color,background-color] duration-150"
						onclick={() => setViewMode('flow')}
						aria-label="Flow view"
					>
						<Workflow size={14} />
					</button>
					<button class="flex items-center justify-center rounded-full p-1.5 bg-surface-2 text-fg" aria-label="List view">
						<List size={14} />
					</button>
				</div>
			{/if}
		</div>

		<div class="relative">
			<Search size={16} class="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-fg-faint" />
			<input
				bind:this={searchEl}
				bind:value={query}
				placeholder="Search agents..."
				class="w-full border border-edge bg-surface-1 py-2 pl-9 pr-8 font-mono text-[13px] text-fg outline-none transition-[border-color,box-shadow] duration-150 placeholder:text-fg-faint focus:border-accent-primary/40 focus:shadow-[0_0_0_3px_oklch(0.91_0.20_128/0.08)]"
			/>
			{#if query}
				<button class="absolute right-3 top-1/2 -translate-y-1/2 text-fg-faint hover:text-fg-muted" onclick={() => (query = '')}><X size={14} /></button>
			{:else}
				<kbd class="absolute right-3 top-1/2 -translate-y-1/2 rounded-full border border-edge bg-surface-2 px-1.5 py-0.5 font-mono text-[11px] text-fg-faint">/</kbd>
			{/if}
		</div>

		{#if !loading}
			<CapabilityFilterBar {agents} {activeFilter} onFilterChange={(f) => (activeFilter = f)} />
		{/if}

		{#if !loading && isFiltering}
			{@const results = filtered()}
			<div class="flex items-center gap-2 text-[13px] text-fg-faint">
				<span class="font-mono" style="font-variant-numeric: tabular-nums">{results.length}</span>
				<span>of {agents.length} agents</span>
				<button class="ml-1 rounded-full border border-edge bg-surface-1 px-2 py-0.5 font-mono text-[12px] text-fg-faint hover:text-fg-muted" onclick={clearFilters}>Clear filters</button>
			</div>
		{/if}

		{#if loading}
			<div class="grid grid-cols-1 gap-2 md:grid-cols-2 lg:grid-cols-3">
				{#each Array(6) as _}
					<Skeleton class="h-28 bg-surface-1" />
				{/each}
			</div>
		{:else}
			{@const results = filtered()}
			{#if results.length === 0 && isFiltering}
				<div class="py-16 text-center">
					<p class="text-[13px] text-fg-faint">No agents match your filters</p>
					<button class="mt-2 text-[13px] text-fg-faint hover:text-fg-muted" onclick={clearFilters}>Clear filters</button>
				</div>
			{:else}
				<AgentList agents={results} onDelete={(agent) => (pendingDelete = agent)} onRun={openQuickRun} />
			{/if}
		{/if}
	</div>

	{#if pendingDelete}
		<ConfirmDeleteDialog
			entityName={pendingDelete.name}
			entityType="agent"
			open={true}
			onConfirm={async () => {
				const id = pendingDelete!.id;
				await deleteAgent(id);
				agents = agents.filter((a) => a.id !== id);
				pendingDelete = null;
			}}
			onCancel={() => (pendingDelete = null)}
		/>
	{/if}
{/if}

{#if drawerAgent}
	<QuickRunDrawer
		agentId={drawerAgent.id}
		agentName={drawerAgent.name}
		onClose={() => (drawerAgent = null)}
	/>
{/if}
