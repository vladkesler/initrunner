<script lang="ts">
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';
	import { fetchComposeList, deleteCompose } from '$lib/api/compose';
	import { getStarters, type StarterInfo } from '$lib/api/builder';
	import type { ComposeSummary } from '$lib/api/types';
	import StarterCard from '$lib/components/ui/StarterCard.svelte';
	import ConfirmDeleteDialog from '$lib/components/ui/ConfirmDeleteDialog.svelte';
	import { Skeleton } from '$lib/components/ui/skeleton';
	import { Search, X, Workflow, Plus, ExternalLink, Trash2 } from 'lucide-svelte';
	import { toast } from '$lib/stores/toast.svelte';

	let composes = $state<ComposeSummary[]>([]);
	let loading = $state(true);
	let query = $state('');
	let pendingDelete: ComposeSummary | null = $state(null);
	let searchEl: HTMLInputElement | undefined = $state();
	let composeStarters = $state<StarterInfo[]>([]);

	const filtered = $derived(() => {
		if (!query.trim()) return composes;
		const q = query.toLowerCase();
		return composes.filter(
			(c) =>
				c.name.toLowerCase().includes(q) ||
				c.description.toLowerCase().includes(q) ||
				c.service_names.some((s) => s.toLowerCase().includes(q))
		);
	});

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === '/' && !e.metaKey && !e.ctrlKey && document.activeElement?.tagName !== 'INPUT') {
			e.preventDefault();
			searchEl?.focus();
		}
	}

	onMount(async () => {
		try {
			const [c, st] = await Promise.all([
				fetchComposeList(),
				getStarters().catch(() => ({ starters: [] }))
			]);
			composes = c;
			composeStarters = st.starters.filter((s) => s.kind === 'Compose');
		} catch {
			toast.error('Failed to load compositions');
		} finally {
			loading = false;
		}
	});
</script>

<svelte:window onkeydown={handleKeydown} />

<div class="space-y-5">
	<!-- Header -->
	<div class="flex items-center justify-between">
		<div class="flex items-center gap-3">
			<h1 class="text-xl font-semibold tracking-[-0.02em] text-fg">Compose</h1>
			{#if !loading}
				<span class="border border-edge bg-surface-1 px-2 py-0.5 font-mono text-[12px] text-fg-faint">{composes.length}</span>
			{/if}
			<a
				href="https://www.initrunner.ai/docs/compose"
				target="_blank"
				rel="noopener"
				class="inline-flex items-center gap-1 font-mono text-[11px] text-accent-primary/60 transition-[color] duration-150 hover:text-accent-primary"
			>
				Docs <ExternalLink size={10} />
			</a>
		</div>
		<a
			href="/compose/new"
			class="flex items-center gap-1.5 rounded-full border border-accent-primary/30 bg-accent-primary/10 px-3 py-1.5 font-mono text-[12px] text-accent-primary transition-[background-color] duration-150 hover:bg-accent-primary/20"
		>
			<Plus size={14} />
			New Compose
		</a>
	</div>

	<!-- Search -->
	{#if composes.length > 0}
		<div class="relative">
			<Search size={16} class="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-fg-faint" />
			<input
				bind:this={searchEl}
				bind:value={query}
				placeholder="Search compositions..."
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
	{/if}

	{#if loading}
		<div class="grid grid-cols-1 gap-2 md:grid-cols-2 lg:grid-cols-3">
			{#each Array(3) as _}
				<Skeleton class="h-28 bg-surface-1" />
			{/each}
		</div>
	{:else if composes.length === 0}
		<!-- Zero state -->
		<div class="flex flex-col items-center justify-center py-20 text-center">
			<div class="mb-4 rounded-full border border-edge bg-surface-1 p-4">
				<Workflow size={28} class="text-fg-faint" />
			</div>
			<h2 class="mb-1 text-[15px] font-medium text-fg">Wire your agents together</h2>
			<p class="mb-6 max-w-sm text-[13px] text-fg-faint">
				Compose creates multi-agent orchestrations that chain, fan-out, or route between your agents.
			</p>
			<a
				href="/compose/new"
				class="flex items-center gap-1.5 rounded-full border border-accent-primary/30 bg-accent-primary/10 px-4 py-2 font-mono text-[13px] text-accent-primary transition-[background-color] duration-150 hover:bg-accent-primary/20"
			>
				<Plus size={14} />
				Create a Composition
			</a>
		</div>

		{#if composeStarters.length > 0}
			<div>
				<h2 class="mb-3 font-mono text-[12px] font-medium uppercase tracking-[0.1em] text-fg-faint">
					Start from a template
				</h2>
				<div class="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
					{#each composeStarters as starter, i}
						<StarterCard {starter} index={i} />
					{/each}
				</div>
			</div>
		{/if}
	{:else}
		{@const results = filtered()}
		{#if results.length === 0 && query}
			<div class="py-16 text-center">
				<p class="text-[13px] text-fg-faint">No compositions match "{query}"</p>
				<button
					class="mt-2 text-[13px] text-fg-faint transition-[color] duration-150 hover:text-fg-muted"
					onclick={() => (query = '')}
				>
					Clear search
				</button>
			</div>
		{:else}
			<div class="grid grid-cols-1 gap-2 md:grid-cols-2 lg:grid-cols-3">
				{#each results as compose, idx}
					<div
						class="group cursor-pointer border border-edge bg-surface-1 p-4 transition-[border-color,background-color,box-shadow] duration-150 hover:border-accent-primary/20 hover:bg-gradient-to-br hover:from-accent-primary/[0.03] hover:to-transparent"
						style="animation: fadeIn 300ms ease-out {idx * 50}ms both"
						role="link"
						tabindex="0"
						onclick={() => goto(`/compose/${compose.id}`)}
						onkeydown={(e) => { if (e.key === 'Enter') goto(`/compose/${compose.id}`); }}
					>
						<div class="flex items-start justify-between gap-2">
							<h3 class="font-mono text-[13px] font-medium text-fg">{compose.name}</h3>
							<div class="flex shrink-0 items-center gap-1.5">
								<span class="border border-edge bg-surface-2 px-1.5 py-0.5 font-mono text-[11px] text-fg-faint">
									{compose.service_count} services
								</span>
								<button
									class="flex items-center justify-center rounded-md p-1 text-fg-faint opacity-0 transition-all duration-150 hover:bg-destructive/10 hover:text-destructive group-hover:opacity-100"
									onclick={(e) => { e.stopPropagation(); pendingDelete = compose; }}
									aria-label="Delete {compose.name}"
								>
									<Trash2 size={13} />
								</button>
							</div>
						</div>
						{#if compose.description}
							<p class="mt-1 text-[12px] text-fg-faint line-clamp-2">{compose.description}</p>
						{/if}
						{#if compose.error}
							<p class="mt-2 border-l-2 border-status-fail/40 pl-2 text-[11px] text-status-fail">{compose.error}</p>
						{:else}
							<div class="mt-2 flex flex-wrap gap-1">
								{#each compose.service_names.slice(0, 5) as svc}
									<span class="rounded-full border border-edge bg-surface-2 px-2 py-0.5 font-mono text-[11px] text-fg-faint">{svc}</span>
								{/each}
								{#if compose.service_names.length > 5}
									<span class="rounded-full border border-edge bg-surface-2 px-2 py-0.5 font-mono text-[11px] text-fg-faint">+{compose.service_names.length - 5}</span>
								{/if}
							</div>
						{/if}
					</div>
				{/each}
			</div>
		{/if}
	{/if}

	{#if pendingDelete}
		<ConfirmDeleteDialog
			entityName={pendingDelete.name}
			entityType="compose"
			open={true}
			onConfirm={async () => {
				const id = pendingDelete!.id;
				await deleteCompose(id);
				composes = composes.filter((c) => c.id !== id);
				pendingDelete = null;
			}}
			onCancel={() => (pendingDelete = null)}
		/>
	{/if}
</div>
