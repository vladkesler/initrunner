<script lang="ts">
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';
	import { listSkills } from '$lib/api/skills';
	import type { SkillSummary } from '$lib/api/types';
	import { toast } from '$lib/stores/toast.svelte';
	import { Skeleton } from '$lib/components/ui/skeleton';
	import SkillList from '$lib/components/skills/SkillList.svelte';
	import { Sparkles, Search } from 'lucide-svelte';

	let skills = $state<SkillSummary[]>([]);
	let loading = $state(true);
	let loadError = $state(false);

	// Filters from URL
	let activeScope = $state('all');
	let activeType = $state('all');
	let query = $state('');

	const filtered = $derived.by(() => {
		let result = skills;
		if (activeScope !== 'all') {
			result = result.filter((s) => s.scope === activeScope);
		}
		if (activeType === 'tools') {
			result = result.filter((s) => s.has_tools);
		} else if (activeType === 'methodology') {
			result = result.filter((s) => !s.has_tools);
		}
		if (query) {
			const q = query.toLowerCase();
			result = result.filter(
				(s) => s.name.toLowerCase().includes(q) || s.description.toLowerCase().includes(q)
			);
		}
		return result;
	});

	const scopeFilters = [
		{ key: 'all', label: 'All' },
		{ key: 'role-local', label: 'Role-local' },
		{ key: 'project', label: 'Project' },
		{ key: 'extra', label: 'Extra' },
		{ key: 'user', label: 'User' }
	];

	const typeFilters = [
		{ key: 'all', label: 'All' },
		{ key: 'tools', label: 'Tool-providing' },
		{ key: 'methodology', label: 'Methodology' }
	];

	function scopeCount(key: string): number {
		if (key === 'all') return skills.length;
		return skills.filter((s) => s.scope === key).length;
	}

	function typeCount(key: string): number {
		if (key === 'all') return skills.length;
		if (key === 'tools') return skills.filter((s) => s.has_tools).length;
		return skills.filter((s) => !s.has_tools).length;
	}

	function setScope(scope: string) {
		activeScope = scope;
		syncUrl();
	}

	function setType(type: string) {
		activeType = type;
		syncUrl();
	}

	function syncUrl() {
		const params = new URLSearchParams();
		if (activeScope !== 'all') params.set('scope', activeScope);
		if (activeType !== 'all') params.set('type', activeType);
		if (query) params.set('search', query);
		const qs = params.toString();
		goto(`/skills${qs ? `?${qs}` : ''}`, { replaceState: true });
	}

	let searchTimer: ReturnType<typeof setTimeout> | null = null;
	function onSearchInput() {
		if (searchTimer) clearTimeout(searchTimer);
		searchTimer = setTimeout(syncUrl, 300);
	}

	onMount(async () => {
		// Restore filters from URL
		const params = page.url.searchParams;
		if (params.has('scope')) activeScope = params.get('scope')!;
		if (params.has('type')) activeType = params.get('type')!;
		if (params.has('search')) query = params.get('search')!;

		try {
			skills = await listSkills();
		} catch {
			toast.error('Failed to load skills');
			loadError = true;
		} finally {
			loading = false;
		}
	});
</script>

<div class="flex h-full flex-col gap-5">
	<!-- Header -->
	<div class="flex items-center gap-3">
		<h1 class="text-xl font-semibold tracking-[-0.02em] text-fg">Skills</h1>
		<span
			class="font-mono text-[13px] text-fg-faint"
			style="font-variant-numeric: tabular-nums"
		>
			{filtered.length}
		</span>
		<a
			href="/skills/new"
			class="ml-auto inline-flex items-center gap-1.5 rounded-full bg-accent-primary px-4 py-1.5 text-[13px] font-medium text-surface-0 transition-[background-color,box-shadow] duration-150 hover:bg-accent-primary-hover hover:shadow-[0_0_16px_oklch(0.91_0.20_128/0.25)]"
		>
			New Skill
		</a>
	</div>

	<!-- Search -->
	<div class="relative">
		<Search
			size={14}
			class="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-fg-faint"
		/>
		<input
			type="text"
			bind:value={query}
			oninput={onSearchInput}
			placeholder="Search skills..."
			class="w-full border border-edge bg-surface-0 py-2 pl-9 pr-3 font-mono text-[13px] text-fg-muted outline-none transition-[border-color,box-shadow] duration-150 focus:border-accent-primary/40 focus:shadow-[0_0_0_3px_oklch(0.91_0.20_128/0.08)]"
		/>
	</div>

	<!-- Filters -->
	<div class="flex flex-col gap-2">
		<!-- Scope -->
		<div class="flex flex-wrap gap-1.5" role="toolbar" aria-label="Filter by scope">
			{#each scopeFilters as f}
				{@const count = scopeCount(f.key)}
				{@const isActive = activeScope === f.key}
				<button
					class="flex shrink-0 items-center gap-1.5 rounded-full border px-3 py-1.5 font-mono text-[12px] transition-[color,background-color,border-color] duration-150
						{isActive
						? f.key === 'role-local'
							? 'border-accent-secondary/30 bg-accent-secondary/10 text-accent-secondary'
							: f.key === 'project'
								? 'border-accent-primary/30 bg-accent-primary/10 text-accent-primary'
								: f.key === 'extra'
									? 'border-warn/30 bg-warn/10 text-warn'
									: 'border-accent-primary/30 bg-accent-primary/10 text-accent-primary'
						: 'border-edge bg-surface-1 text-fg-faint hover:text-fg-muted'}"
					onclick={() => setScope(f.key)}
					aria-pressed={isActive}
				>
					<span>{f.label}</span>
					<span class="opacity-50">({count})</span>
				</button>
			{/each}
		</div>

		<!-- Type -->
		<div class="flex flex-wrap gap-1.5" role="toolbar" aria-label="Filter by type">
			{#each typeFilters as f}
				{@const count = typeCount(f.key)}
				{@const isActive = activeType === f.key}
				<button
					class="flex shrink-0 items-center gap-1.5 rounded-full border px-3 py-1.5 font-mono text-[12px] transition-[color,background-color,border-color] duration-150
						{isActive
						? 'border-accent-primary/30 bg-accent-primary/10 text-accent-primary'
						: 'border-edge bg-surface-1 text-fg-faint hover:text-fg-muted'}"
					onclick={() => setType(f.key)}
					aria-pressed={isActive}
				>
					<span>{f.label}</span>
					<span class="opacity-50">({count})</span>
				</button>
			{/each}
		</div>
	</div>

	<!-- Content -->
	{#if loading}
		<div class="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
			{#each Array(6) as _}
				<Skeleton class="h-[140px] bg-surface-1" />
			{/each}
		</div>
	{:else if loadError}
		<div class="flex flex-col items-center gap-4 py-16 text-center">
			<p class="text-[13px] text-fg-faint">Failed to load skills.</p>
			<button
				class="rounded-full border border-edge px-4 py-1.5 text-[13px] text-fg-faint hover:text-fg-muted"
				onclick={() => location.reload()}
			>
				Retry
			</button>
		</div>
	{:else if skills.length === 0}
		<div class="flex flex-col items-center gap-4 py-16 text-center">
			<Sparkles size={32} class="text-fg-faint" />
			<h2 class="text-[15px] font-medium text-fg-muted">No skills yet</h2>
			<p class="max-w-sm text-[13px] text-fg-faint">
				Skills augment agents with reusable tools and methodology prompts.
			</p>
			<a
				href="/skills/new"
				class="rounded-full bg-accent-primary px-5 py-2 text-[13px] font-medium text-surface-0 transition-[background-color,box-shadow] duration-150 hover:bg-accent-primary-hover hover:shadow-[0_0_16px_oklch(0.91_0.20_128/0.25)]"
			>
				Create your first skill
			</a>
		</div>
	{:else if filtered.length === 0}
		<div class="flex flex-col items-center gap-4 py-16 text-center">
			<p class="text-[13px] text-fg-faint">No skills match the current filters.</p>
		</div>
	{:else}
		<SkillList skills={filtered} />
	{/if}
</div>
