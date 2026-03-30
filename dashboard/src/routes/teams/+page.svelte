<script lang="ts">
	import { onMount } from 'svelte';
	import { fetchTeamList, deleteTeam } from '$lib/api/teams';
	import { getStarters, type StarterInfo } from '$lib/api/builder';
	import type { TeamSummary } from '$lib/api/types';
	import TeamList from '$lib/components/teams/TeamList.svelte';
	import StarterCard from '$lib/components/ui/StarterCard.svelte';
	import ConfirmDeleteDialog from '$lib/components/ui/ConfirmDeleteDialog.svelte';
	import { Skeleton } from '$lib/components/ui/skeleton';
	import { Search, X, Users, Plus } from 'lucide-svelte';
	import { toast } from '$lib/stores/toast.svelte';

	let teams = $state<TeamSummary[]>([]);
	let loading = $state(true);
	let query = $state('');
	let pendingDelete: TeamSummary | null = $state(null);
	let searchEl: HTMLInputElement | undefined = $state();
	let teamStarters = $state<StarterInfo[]>([]);

	const filtered = $derived(() => {
		if (!query.trim()) return teams;
		const q = query.toLowerCase();
		return teams.filter(
			(t) =>
				t.name.toLowerCase().includes(q) ||
				t.description.toLowerCase().includes(q) ||
				t.persona_names.some((p) => p.toLowerCase().includes(q))
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
			const [t, st] = await Promise.all([
				fetchTeamList(),
				getStarters().catch(() => ({ starters: [] }))
			]);
			teams = t;
			teamStarters = st.starters.filter((s) => s.kind === 'Team');
		} catch {
			toast.error('Failed to load teams');
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
			<h1 class="text-xl font-semibold tracking-[-0.02em] text-fg">Teams</h1>
			{#if !loading}
				<span class="border border-edge bg-surface-1 px-2 py-0.5 font-mono text-[12px] text-fg-faint">{teams.length}</span>
			{/if}
		</div>
		<a
			href="/teams/new"
			class="flex items-center gap-1.5 rounded-full border border-accent-primary/30 bg-accent-primary/10 px-3 py-1.5 font-mono text-[12px] text-accent-primary transition-[background-color] duration-150 hover:bg-accent-primary/20"
		>
			<Plus size={14} />
			New Team
		</a>
	</div>

	<!-- Search -->
	{#if teams.length > 0}
		<div class="relative">
			<Search size={16} class="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-fg-faint" />
			<input
				bind:this={searchEl}
				bind:value={query}
				placeholder="Search teams..."
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
	{:else if teams.length === 0}
		<!-- Zero state -->
		<div class="flex flex-col items-center justify-center py-20 text-center">
			<div class="mb-4 rounded-full border border-edge bg-surface-1 p-4">
				<Users size={28} class="text-fg-faint" />
			</div>
			<h2 class="mb-1 text-[15px] font-medium text-fg">Assemble a multi-persona team</h2>
			<p class="mb-6 max-w-sm text-[13px] text-fg-faint">
				Teams coordinate multiple AI personas using sequential or parallel strategies to tackle tasks collaboratively.
			</p>
			<a
				href="/teams/new"
				class="flex items-center gap-1.5 rounded-full border border-accent-primary/30 bg-accent-primary/10 px-4 py-2 font-mono text-[13px] text-accent-primary transition-[background-color] duration-150 hover:bg-accent-primary/20"
			>
				<Plus size={14} />
				Create a Team
			</a>
		</div>

		{#if teamStarters.length > 0}
			<div>
				<h2 class="mb-3 font-mono text-[12px] font-medium uppercase tracking-[0.1em] text-fg-faint">
					Start from a template
				</h2>
				<div class="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
					{#each teamStarters as starter, i}
						<StarterCard {starter} index={i} />
					{/each}
				</div>
			</div>
		{/if}
	{:else}
		{@const results = filtered()}
		{#if results.length === 0 && query}
			<div class="py-16 text-center">
				<p class="text-[13px] text-fg-faint">No teams match "{query}"</p>
				<button
					class="mt-2 text-[13px] text-fg-faint transition-[color] duration-150 hover:text-fg-muted"
					onclick={() => (query = '')}
				>
					Clear search
				</button>
			</div>
		{:else}
			<TeamList teams={results} onDelete={(team) => (pendingDelete = team)} />
		{/if}
	{/if}

	{#if pendingDelete}
		<ConfirmDeleteDialog
			entityName={pendingDelete.name}
			entityType="team"
			open={true}
			onConfirm={async () => {
				const id = pendingDelete!.id;
				await deleteTeam(id);
				teams = teams.filter((t) => t.id !== id);
				pendingDelete = null;
			}}
			onCancel={() => (pendingDelete = null)}
		/>
	{/if}
</div>
