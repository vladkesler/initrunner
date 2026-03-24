<script lang="ts">
	import { Search, X, ChevronDown } from 'lucide-svelte';
	import type { AgentSlotOption } from '$lib/api/types';

	let {
		agents,
		selected = null,
		onSelect,
		placeholder = 'Select agent...',
		noneLabel = ''
	}: {
		agents: AgentSlotOption[];
		selected: string | null;
		onSelect: (agent: AgentSlotOption | null) => void;
		placeholder?: string;
		noneLabel?: string;
	} = $props();

	let open = $state(false);
	let query = $state('');
	let highlightIndex = $state(-1);
	let triggerEl: HTMLDivElement | undefined = $state();
	let panelEl: HTMLDivElement | undefined = $state();
	let searchEl: HTMLInputElement | undefined = $state();

	const selectedAgent = $derived(selected ? agents.find((a) => a.id === selected) ?? null : null);

	const filtered = $derived(() => {
		if (!query) return agents;
		const q = query.toLowerCase();
		return agents.filter(
			(a) =>
				a.name.toLowerCase().includes(q) ||
				a.description.toLowerCase().includes(q) ||
				a.tags.some((t) => t.toLowerCase().includes(q)) ||
				a.features.some((f) => f.toLowerCase().includes(q)) ||
				a.path.toLowerCase().includes(q)
		);
	});

	function toggle() {
		open = !open;
		if (open) {
			query = '';
			highlightIndex = -1;
			requestAnimationFrame(() => searchEl?.focus());
		}
	}

	function close() {
		open = false;
	}

	function select(agent: AgentSlotOption | null) {
		onSelect(agent);
		close();
	}

	function handleWindowClick(e: MouseEvent) {
		if (!open) return;
		const target = e.target as Node;
		// After a selection the panel is destroyed, so panelEl may be null.
		// Check the trigger; everything else closes the picker.
		if (triggerEl?.contains(target)) return;
		if (panelEl && panelEl.contains(target)) return;
		close();
	}

	function handleKeydown(e: KeyboardEvent) {
		if (!open) return;
		const items = filtered();
		const total = items.length + (noneLabel ? 1 : 0);

		if (e.key === 'ArrowDown') {
			e.preventDefault();
			highlightIndex = (highlightIndex + 1) % total;
		} else if (e.key === 'ArrowUp') {
			e.preventDefault();
			highlightIndex = (highlightIndex - 1 + total) % total;
		} else if (e.key === 'Enter') {
			e.preventDefault();
			if (noneLabel && highlightIndex === 0) {
				select(null);
			} else {
				const idx = noneLabel ? highlightIndex - 1 : highlightIndex;
				if (idx >= 0 && idx < items.length) {
					select(items[idx]);
				}
			}
		} else if (e.key === 'Escape') {
			e.preventDefault();
			close();
		}
	}

	function modelLabel(agent: AgentSlotOption): string {
		if (!agent.model) return '';
		const { provider, name } = agent.model;
		return provider ? `${provider}/${name}` : name;
	}

	function clearSelection(e: MouseEvent) {
		e.stopPropagation();
		select(null);
	}
</script>

<svelte:window onclick={handleWindowClick} />

<div class="relative">
	<!-- Trigger -->
	<!-- svelte-ignore a11y_click_events_have_key_events -->
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div
		bind:this={triggerEl}
		class="flex cursor-pointer items-center gap-1.5 border bg-surface-1 px-2 py-1.5 transition-[border-color] duration-150 {open ? 'border-accent-primary/40' : 'border-edge hover:border-fg-faint/40'}"
		onclick={toggle}
	>
		{#if selectedAgent}
			<span class="min-w-0 flex-1 truncate font-mono text-[12px] text-fg">{selectedAgent.name}</span>
			{#if selectedAgent.model}
				<span class="hidden shrink-0 rounded-full border border-edge bg-surface-2 px-1.5 py-0.5 font-mono text-[10px] text-fg-faint sm:inline">
					{modelLabel(selectedAgent)}
				</span>
			{/if}
			<button
				class="shrink-0 p-0.5 text-fg-faint transition-[color] duration-150 hover:text-fg-muted"
				onclick={clearSelection}
				aria-label="Clear selection"
			>
				<X size={12} />
			</button>
		{:else}
			<span class="min-w-0 flex-1 truncate font-mono text-[12px] text-fg-faint">{placeholder}</span>
			<ChevronDown size={12} class="shrink-0 text-fg-faint" />
		{/if}
	</div>

	<!-- Dropdown panel -->
	{#if open}
		<!-- svelte-ignore a11y_no_noninteractive_tabindex -->
		<div
			bind:this={panelEl}
			role="listbox"
			tabindex="0"
			class="absolute top-full left-0 z-50 mt-1 w-full min-w-[280px] border border-edge bg-surface-1 shadow-lg"
			onkeydown={handleKeydown}
		>
			<!-- Search -->
			<div class="relative border-b border-edge">
				<Search size={12} class="absolute top-1/2 left-2.5 -translate-y-1/2 text-fg-faint" />
				<input
					bind:this={searchEl}
					bind:value={query}
					type="text"
					placeholder="Search agents..."
					class="w-full bg-transparent py-2 pr-2.5 pl-7 font-mono text-[12px] text-fg outline-none placeholder:text-fg-faint"
				/>
			</div>

			<!-- List -->
			<div class="max-h-64 overflow-y-auto">
				{#if noneLabel}
					<!-- svelte-ignore a11y_click_events_have_key_events -->
					<!-- svelte-ignore a11y_no_static_element_interactions -->
					<div
						class="cursor-pointer border-b border-edge/50 px-3 py-2 text-[12px] text-fg-faint transition-[background-color] duration-150 hover:bg-accent-primary/[0.03] {highlightIndex === 0 ? 'bg-accent-primary/[0.06]' : ''}"
						onclick={() => select(null)}
					>
						{noneLabel}
					</div>
				{/if}

				{#each filtered() as agent, idx}
					{@const itemIndex = noneLabel ? idx + 1 : idx}
					{@const isSelected = agent.id === selected}
					{@const isHighlighted = highlightIndex === itemIndex || isSelected}
					<!-- svelte-ignore a11y_click_events_have_key_events -->
					<!-- svelte-ignore a11y_no_static_element_interactions -->
					<div
						class="cursor-pointer px-3 py-2 transition-[background-color,border-color] duration-150 hover:bg-accent-primary/[0.03] {isHighlighted ? 'bg-accent-primary/[0.06]' : ''} {isSelected ? 'border-l-2 border-l-accent-primary pl-2.5' : ''}"
						onclick={() => select(agent)}
					>
						<!-- Name + model -->
						<div class="flex items-center gap-2">
							<span class="min-w-0 flex-1 truncate font-mono text-[13px] text-fg">{agent.name}</span>
							{#if agent.model}
								<span class="shrink-0 rounded-full border border-edge bg-surface-2 px-1.5 py-0.5 font-mono text-[10px] text-fg-faint">
									{modelLabel(agent)}
								</span>
							{/if}
						</div>

						<!-- Description -->
						{#if agent.description}
							<p class="mt-0.5 truncate text-[12px] text-fg-faint">{agent.description}</p>
						{/if}

						<!-- Feature pills -->
						{#if agent.features.length > 0}
							<div class="mt-1 flex flex-wrap gap-1">
								{#each agent.features.slice(0, 3) as feature}
									<span class="rounded-full border border-edge bg-surface-2 px-1.5 py-0.5 font-mono text-[10px] text-fg-faint">
										{feature}
									</span>
								{/each}
								{#if agent.features.length > 3}
									<span class="rounded-full border border-edge bg-surface-2 px-1.5 py-0.5 font-mono text-[10px] text-fg-faint">
										+{agent.features.length - 3}
									</span>
								{/if}
							</div>
						{/if}
					</div>
				{/each}

				{#if filtered().length === 0}
					<div class="px-3 py-4 text-center font-mono text-[12px] text-fg-faint">No agents match</div>
				{/if}
			</div>
		</div>
	{/if}
</div>
