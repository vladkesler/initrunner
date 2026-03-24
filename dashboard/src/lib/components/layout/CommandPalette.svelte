<script lang="ts">
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';
	import { Search, Blocks, ScanEye, Cpu, Compass, Plus } from 'lucide-svelte';
	import { listAgents } from '$lib/api/agents';
	import type { AgentSummary } from '$lib/api/types';

	let open = $state(false);
	let query = $state('');
	let agents = $state<AgentSummary[]>([]);
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
		{ id: 'nav-audit', label: 'Audit', href: '/audit', icon: ScanEye, group: 'Pages' },
		{ id: 'nav-system', label: 'System', href: '/system', icon: Cpu, group: 'Pages' },
		{ id: 'action-new', label: 'New Agent', href: '/agents/new', icon: Plus, group: 'Actions' }
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
		return [...staticItems, ...agentItems];
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
		open = !open;
		if (open) {
			query = '';
			selectedIndex = 0;
			loadAgents();
			// Focus input after render
			requestAnimationFrame(() => inputEl?.focus());
		}
	}

	function navigate(href: string) {
		open = false;
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
			open = false;
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

	async function loadAgents() {
		try {
			agents = await listAgents();
		} catch {
			// API not available
		}
	}

	onMount(loadAgents);
</script>

<svelte:window onkeydown={handleKeydown} />

{#if open}
	<!-- Backdrop -->
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div
		class="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm"
		onclick={() => (open = false)}
		onkeydown={(e) => e.key === 'Escape' && (open = false)}
	>
		<!-- Panel -->
		<!-- svelte-ignore a11y_no_static_element_interactions -->
		<div
			class="mx-auto mt-[15vh] w-full max-w-lg border border-accent-primary/10 bg-surface-1 shadow-2xl"
			onclick={(e) => e.stopPropagation()}
			onkeydown={(e) => e.stopPropagation()}
		>
			<!-- Search input -->
			<div class="flex items-center gap-3 border-b border-edge px-4 py-3">
				<Search size={16} class="shrink-0 text-accent-primary/50" />
				<input
					bind:this={inputEl}
					bind:value={query}
					placeholder="Search agents, pages, actions..."
					class="w-full bg-transparent text-[14px] text-fg outline-none placeholder:text-fg-faint"
				/>
				<kbd class="shrink-0 rounded-full border border-edge bg-surface-2 px-2 py-0.5 font-mono text-[12px] text-fg-faint">ESC</kbd>
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
						<div class="px-3 pb-1 pt-2 font-mono text-[11px] font-medium uppercase tracking-[0.12em] text-fg-faint">
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
				<span><kbd class="rounded-full border border-edge px-1.5">&#8593;&#8595;</kbd> navigate</span>
				<span><kbd class="rounded-full border border-edge px-1.5">&#8629;</kbd> select</span>
				<span><kbd class="rounded-full border border-edge px-1.5">esc</kbd> close</span>
			</div>
		</div>
	</div>
{/if}
