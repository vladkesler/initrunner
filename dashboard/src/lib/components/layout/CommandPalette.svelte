<script lang="ts">
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';
	import { Search, Blocks, ScanEye, Cpu, Compass, Plus, Users, Workflow } from 'lucide-svelte';
	import { listAgents } from '$lib/api/agents';
	import { fetchFlowList } from '$lib/api/flow';
	import { fetchTeamList } from '$lib/api/teams';
	import type { AgentSummary, FlowSummary, TeamSummary } from '$lib/api/types';
	import { isPaletteOpen, togglePalette, closePalette, openPalette } from '$lib/stores/command-palette.svelte';

	const open = $derived(isPaletteOpen());
	let query = $state('');
	let agents = $state<AgentSummary[]>([]);
	let flows = $state<FlowSummary[]>([]);
	let teams = $state<TeamSummary[]>([]);
	let selectedIndex = $state(0);
	let inputEl: HTMLInputElement | undefined = $state();

	interface PaletteItem {
		id: string;
		label: string;
		sublabel?: string;
		href: string;
		icon: typeof Blocks;
		group: string;
	}

	const staticItems: PaletteItem[] = [
		{ id: 'nav-launchpad', label: 'Launchpad', href: '/', icon: Compass, group: 'Pages' },
		{ id: 'nav-agents', label: 'Agents', href: '/agents', icon: Blocks, group: 'Pages' },
		{ id: 'nav-flows', label: 'Flows', href: '/flows', icon: Workflow, group: 'Pages' },
		{ id: 'nav-audit', label: 'Audit', href: '/audit', icon: ScanEye, group: 'Pages' },
		{ id: 'nav-teams', label: 'Teams', href: '/teams', icon: Users, group: 'Pages' },
		{ id: 'nav-system', label: 'System', href: '/system', icon: Cpu, group: 'Pages' },
		{ id: 'action-new', label: 'New Agent', href: '/agents/new', icon: Plus, group: 'Actions' },
		{ id: 'action-new-flow', label: 'New Flow', href: '/flows/new', icon: Plus, group: 'Actions' },
		{ id: 'action-new-team', label: 'New Team', href: '/teams/new', icon: Plus, group: 'Actions' }
	];

	const allItems = $derived.by(() => {
		const agentItems: PaletteItem[] = agents.map((a) => ({
			id: `agent-${a.id}`,
			label: a.name,
			sublabel: a.description,
			href: `/agents/${a.id}`,
			icon: Blocks,
			group: 'Agents'
		}));
		const flowItems: PaletteItem[] = flows.map((c) => ({
			id: `flow-${c.id}`,
			label: c.name,
			sublabel: c.description,
			href: `/flows/${c.id}`,
			icon: Workflow,
			group: 'Flows'
		}));
		const teamItems: PaletteItem[] = teams.map((t) => ({
			id: `team-${t.id}`,
			label: t.name,
			sublabel: t.description,
			href: `/teams/${t.id}`,
			icon: Users,
			group: 'Teams'
		}));
		return [...staticItems, ...agentItems, ...flowItems, ...teamItems];
	});

	const filtered = $derived.by(() => {
		if (!query.trim()) return allItems;
		const q = query.toLowerCase();
		return allItems.filter(
			(item) =>
				item.label.toLowerCase().includes(q) ||
				(item.sublabel && item.sublabel.toLowerCase().includes(q))
		);
	});

	// Group items for display
	const grouped = $derived.by(() => {
		const groups = new Map<string, PaletteItem[]>();
		for (const item of filtered) {
			const list = groups.get(item.group) || [];
			list.push(item);
			groups.set(item.group, list);
		}
		return groups;
	});

	const flatFiltered = $derived(filtered);

	$effect(() => {
		// Reset selection when query changes
		query;
		selectedIndex = 0;
	});

	function toggle() {
		togglePalette();
		if (isPaletteOpen()) {
			query = '';
			selectedIndex = 0;
			loadData();
			requestAnimationFrame(() => inputEl?.focus());
		}
	}

	// Focus input when palette opens externally (e.g. header button)
	$effect(() => {
		if (isPaletteOpen()) {
			query = '';
			selectedIndex = 0;
			loadData();
			requestAnimationFrame(() => inputEl?.focus());
		}
	});

	function navigate(href: string) {
		closePalette();
		goto(href);
	}

	function handleKeydown(e: KeyboardEvent) {
		if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
			e.preventDefault();
			toggle();
			return;
		}
		if (!open) return;

		if (e.key === 'Escape') {
			e.preventDefault();
			closePalette();
		} else if (e.key === 'ArrowDown') {
			e.preventDefault();
			selectedIndex = Math.min(selectedIndex + 1, flatFiltered.length - 1);
		} else if (e.key === 'ArrowUp') {
			e.preventDefault();
			selectedIndex = Math.max(selectedIndex - 1, 0);
		} else if (e.key === 'Enter') {
			e.preventDefault();
			const item = flatFiltered[selectedIndex];
			if (item) navigate(item.href);
		}
	}

	async function loadData() {
		try {
			const [a, c, t] = await Promise.all([
				listAgents().catch(() => [] as AgentSummary[]),
				fetchFlowList().catch(() => [] as FlowSummary[]),
				fetchTeamList().catch(() => [] as TeamSummary[])
			]);
			agents = a;
			flows = c;
			teams = t;
		} catch {
			// API not available
		}
	}

	onMount(loadData);
</script>

<svelte:window onkeydown={handleKeydown} />

{#if open}
	<!-- Backdrop -->
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div
		class="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm"
		onclick={() => closePalette()}
		onkeydown={(e) => e.key === 'Escape' && closePalette()}
	>
		<!-- Panel -->
		<!-- svelte-ignore a11y_no_static_element_interactions -->
		<div
			class="mx-auto mt-[20vh] w-full max-w-lg border border-accent-primary-dim/40 bg-surface-1 shadow-2xl"
			onclick={(e) => e.stopPropagation()}
			onkeydown={(e) => e.stopPropagation()}
		>
			<!-- Search input -->
			<div class="flex items-center gap-3 border-b border-edge px-4 py-3">
				<Search size={16} class="shrink-0 text-accent-primary/50" />
				<input
					bind:this={inputEl}
					bind:value={query}
					placeholder="Search agents, flows, teams..."
					class="w-full bg-transparent text-[14px] text-fg outline-none placeholder:text-fg-faint"
				/>
				<kbd class="shrink-0 rounded-[2px] border border-edge bg-surface-2 px-2 py-0.5 font-mono text-[12px] text-fg-faint">ESC</kbd>
			</div>

			<!-- Results -->
			<div class="max-h-[50vh] overflow-y-auto py-2">
				{#if flatFiltered.length === 0}
					<div class="px-4 py-8 text-center text-[13px] text-fg-faint">
						No results for "{query}"
					</div>
				{:else}
					{@const flatIndex = { value: 0 }}
					{#each grouped as [group, items]}
						<div class="px-3 pb-1 pt-2 section-label">
							{group}
						</div>
						{#each items as item}
							{@const idx = flatIndex.value++}
							<button
								class="flex w-full items-center gap-3 px-4 py-2 text-left text-[13px] transition-[background-color] duration-100 {idx === selectedIndex ? 'bg-accent-primary/[0.08] text-fg' : 'text-fg-muted'}"
								onmouseenter={() => (selectedIndex = idx)}
								onclick={() => navigate(item.href)}
							>
								<item.icon size={14} strokeWidth={1.75} class="shrink-0 text-fg-faint" />
								<span class="truncate">{item.label}</span>
								{#if item.sublabel}
									<span class="ml-auto truncate text-[13px] text-fg-faint">{item.sublabel}</span>
								{/if}
							</button>
						{/each}
					{/each}
				{/if}
			</div>

			<!-- Footer -->
			<div class="flex items-center gap-4 border-t border-edge px-4 py-2 font-mono text-[12px] text-fg-faint">
				<span><kbd class="rounded-[2px] border border-edge px-1.5">&#8593;&#8595;</kbd> navigate</span>
				<span><kbd class="rounded-[2px] border border-edge px-1.5">&#8629;</kbd> select</span>
				<span><kbd class="rounded-[2px] border border-edge px-1.5">esc</kbd> close</span>
			</div>
		</div>
	</div>
{/if}
