<script lang="ts">
	import { onMount } from 'svelte';
	import { listAgents } from '$lib/api/agents';
	import type { AgentSummary } from '$lib/api/types';
	import AgentList from '$lib/components/agents/AgentList.svelte';
	import { Skeleton } from '$lib/components/ui/skeleton';
	import { Search, LayoutGrid, List, X } from 'lucide-svelte';
	import { safeGet, safeSet } from '$lib/utils/storage';

	let agents = $state<AgentSummary[]>([]);
	let loading = $state(true);
	let query = $state('');
	let activeTags = $state<Set<string>>(new Set());
	let viewMode = $state<'grid' | 'list'>('grid');
	let searchEl: HTMLInputElement | undefined = $state();

	// Extract unique tags
	const allTags = $derived(
		[...new Set(agents.flatMap((a) => a.tags))].sort()
	);

	// Filter agents
	const filtered = $derived(() => {
		let result = agents;
		if (query.trim()) {
			const q = query.toLowerCase();
			result = result.filter(
				(a) =>
					a.name.toLowerCase().includes(q) ||
					a.description.toLowerCase().includes(q) ||
					a.tags.some((t) => t.toLowerCase().includes(q)) ||
					a.model.toLowerCase().includes(q) ||
					a.provider.toLowerCase().includes(q)
			);
		}
		if (activeTags.size > 0) {
			result = result.filter((a) => a.tags.some((t) => activeTags.has(t)));
		}
		return result;
	});

	function toggleTag(tag: string) {
		const next = new Set(activeTags);
		if (next.has(tag)) next.delete(tag);
		else next.add(tag);
		activeTags = next;
	}

	function clearSearch() {
		query = '';
		activeTags = new Set();
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === '/' && !e.metaKey && !e.ctrlKey && document.activeElement?.tagName !== 'INPUT') {
			e.preventDefault();
			searchEl?.focus();
		}
	}

	onMount(async () => {
		try {
			const stored = safeGet('agents-view-mode');
			if (stored === 'list' || stored === 'grid') viewMode = stored;
			agents = await listAgents();
		} catch {
			// API or storage not available
		} finally {
			loading = false;
		}
	});

	function setViewMode(mode: 'grid' | 'list') {
		viewMode = mode;
		safeSet('agents-view-mode', mode);
	}
</script>

<svelte:window onkeydown={handleKeydown} />

<div class="space-y-5">
	<!-- Header -->
	<div class="flex items-center justify-between">
		<div class="flex items-center gap-3">
			<h1 class="text-xl font-semibold tracking-[-0.02em] text-fg">Agents</h1>
			{#if !loading}
				<span class="border border-edge bg-surface-1 px-2 py-0.5 font-mono text-[12px] text-fg-faint">{agents.length}</span>
			{/if}
		</div>
		<!-- View toggle -->
		<div class="flex items-center gap-0.5 rounded-full border border-edge bg-surface-1 p-0.5">
			<button
				class="flex items-center justify-center rounded-full p-1.5 transition-[color,background-color] duration-150"
				class:bg-surface-2={viewMode === 'grid'}
				class:text-fg={viewMode === 'grid'}
				class:text-fg-faint={viewMode !== 'grid'}
				onclick={() => setViewMode('grid')}
				aria-label="Grid view"
			>
				<LayoutGrid size={14} />
			</button>
			<button
				class="flex items-center justify-center rounded-full p-1.5 transition-[color,background-color] duration-150"
				class:bg-surface-2={viewMode === 'list'}
				class:text-fg={viewMode === 'list'}
				class:text-fg-faint={viewMode !== 'list'}
				onclick={() => setViewMode('list')}
				aria-label="List view"
			>
				<List size={14} />
			</button>
		</div>
	</div>

	<!-- Search -->
	<div class="relative">
		<Search size={16} class="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-fg-faint" />
		<input
			bind:this={searchEl}
			bind:value={query}
			placeholder="Search agents..."
			class="w-full border border-edge bg-surface-1 py-2 pl-9 pr-8 font-mono text-[13px] text-fg outline-none transition-[border-color,box-shadow] duration-150 placeholder:text-fg-faint focus:border-accent-primary/40 focus:shadow-[0_0_0_3px_oklch(0.91_0.20_128/0.08)]"
		/>
		{#if query}
			<button
				class="absolute right-3 top-1/2 -translate-y-1/2 text-fg-faint transition-[color] duration-150 hover:text-fg-muted"
				onclick={() => (query = '')}
				aria-label="Clear search"
			>
				<X size={14} />
			</button>
		{/if}
	</div>

	<!-- Tag filters -->
	{#if allTags.length > 0}
		<div class="flex flex-wrap gap-1.5">
			{#each allTags as tag}
				<button
					class="rounded-full border px-2.5 py-0.5 font-mono text-[12px] transition-[color,background-color,border-color] duration-150 {activeTags.has(tag) ? 'border-accent-primary/30 bg-accent-primary/10 text-accent-primary' : 'border-edge bg-surface-1 text-fg-faint'}"
					onclick={() => toggleTag(tag)}
				>
					{tag}
				</button>
			{/each}
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
		{#if results.length === 0 && (query || activeTags.size > 0)}
			<div class="py-16 text-center">
				<p class="text-[13px] text-fg-faint">No agents match "{query || [...activeTags].join(', ')}"</p>
				<button
					class="mt-2 text-[13px] text-fg-faint transition-[color] duration-150 hover:text-fg-muted"
					onclick={clearSearch}
				>
					Clear filters
				</button>
			</div>
		{:else}
			<AgentList agents={results} {viewMode} />
		{/if}
	{/if}
</div>
