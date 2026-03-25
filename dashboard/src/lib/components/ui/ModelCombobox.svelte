<script lang="ts">
	import { Search, ChevronDown, Pencil, ArrowLeft } from 'lucide-svelte';

	let {
		models = [],
		value = $bindable(''),
		compact = false
	}: {
		models: { name: string; description: string }[];
		value: string;
		compact?: boolean;
	} = $props();

	let open = $state(false);
	let query = $state('');
	let customMode = $state(false);
	let highlightIndex = $state(-1);
	let triggerEl: HTMLDivElement | undefined = $state();
	let panelEl: HTMLDivElement | undefined = $state();
	let inputEl: HTMLInputElement | undefined = $state();

	const filtered = $derived(() => {
		if (!query) return models;
		const q = query.toLowerCase();
		return models.filter(
			(m) => m.name.toLowerCase().includes(q) || m.description.toLowerCase().includes(q)
		);
	});

	function toggle() {
		open = !open;
		if (open) {
			query = '';
			customMode = false;
			highlightIndex = -1;
			requestAnimationFrame(() => inputEl?.focus());
		}
	}

	function close() {
		open = false;
		customMode = false;
	}

	function select(model: string) {
		value = model;
		close();
	}

	function enterCustomMode() {
		customMode = true;
		query = '';
		highlightIndex = -1;
		requestAnimationFrame(() => inputEl?.focus());
	}

	function exitCustomMode() {
		customMode = false;
		query = '';
		highlightIndex = -1;
		requestAnimationFrame(() => inputEl?.focus());
	}

	function handleWindowClick(e: MouseEvent) {
		if (!open) return;
		const target = e.target as Node;
		if (triggerEl?.contains(target)) return;
		if (panelEl && panelEl.contains(target)) return;
		close();
	}

	function handleKeydown(e: KeyboardEvent) {
		if (!open) return;

		if (customMode) {
			if (e.key === 'Enter') {
				e.preventDefault();
				if (query.trim()) select(query.trim());
			} else if (e.key === 'Escape') {
				e.preventDefault();
				close();
			}
			return;
		}

		const items = filtered();
		// +1 for the "Enter custom model" footer row
		const total = items.length + 1;

		if (e.key === 'ArrowDown') {
			e.preventDefault();
			highlightIndex = (highlightIndex + 1) % total;
		} else if (e.key === 'ArrowUp') {
			e.preventDefault();
			highlightIndex = (highlightIndex - 1 + total) % total;
		} else if (e.key === 'Enter') {
			e.preventDefault();
			if (highlightIndex >= 0 && highlightIndex < items.length) {
				select(items[highlightIndex].name);
			} else if (highlightIndex === items.length) {
				enterCustomMode();
			}
		} else if (e.key === 'Escape') {
			e.preventDefault();
			close();
		}
	}

	const triggerClass = $derived(
		compact
			? 'flex cursor-pointer items-center gap-1.5 border bg-surface-1 px-2 py-1 transition-[border-color] duration-150'
			: 'flex cursor-pointer items-center gap-1.5 border bg-surface-1 px-3 py-2 transition-[border-color] duration-150'
	);

	const textClass = $derived(
		compact ? 'font-mono text-[12px]' : 'font-mono text-[13px]'
	);
</script>

<svelte:window onclick={handleWindowClick} />

<div class="relative min-w-0 flex-1">
	<!-- Trigger -->
	<!-- svelte-ignore a11y_click_events_have_key_events -->
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div
		bind:this={triggerEl}
		class="{triggerClass} {open ? 'border-accent-primary/40' : 'border-edge hover:border-fg-faint/40'}"
		onclick={toggle}
	>
		<span class="min-w-0 flex-1 truncate {textClass} {value ? 'text-fg' : 'text-fg-faint'}">
			{value || 'Select model...'}
		</span>
		<ChevronDown size={compact ? 11 : 12} class="shrink-0 text-fg-faint transition-transform duration-150 {open ? 'rotate-180' : ''}" />
	</div>

	<!-- Dropdown panel -->
	{#if open}
		<!-- svelte-ignore a11y_no_noninteractive_tabindex -->
		<div
			bind:this={panelEl}
			role="listbox"
			tabindex="0"
			class="absolute top-full left-0 z-50 mt-1 w-full min-w-[260px] border border-edge bg-surface-1 shadow-lg"
			onkeydown={handleKeydown}
		>
			{#if customMode}
				<!-- Custom model entry -->
				<div class="px-3 pt-2.5 pb-1">
					<span class="font-mono text-[11px] font-medium uppercase tracking-[0.08em] text-fg-faint">Custom model</span>
				</div>
				<div class="px-3 pb-2">
					<input
						bind:this={inputEl}
						bind:value={query}
						type="text"
						placeholder="Type model ID..."
						class="w-full border border-edge bg-surface-2 px-2.5 py-1.5 font-mono text-[12px] text-fg outline-none transition-[border-color] duration-150 placeholder:text-fg-faint focus:border-accent-primary/40"
						onkeydown={(e) => {
							if (e.key === 'Enter' && query.trim()) {
								e.preventDefault();
								select(query.trim());
							}
						}}
					/>
				</div>
				<div class="flex items-center justify-between border-t border-edge px-3 py-2">
					<button
						class="flex items-center gap-1 font-mono text-[11px] text-fg-faint transition-[color] duration-150 hover:text-fg-muted"
						onclick={(e) => { e.stopPropagation(); exitCustomMode(); }}
					>
						<ArrowLeft size={10} />
						Back to list
					</button>
					<button
						class="font-mono text-[11px] text-accent-primary transition-[opacity] duration-150 {query.trim() ? 'opacity-100' : 'opacity-30'}"
						disabled={!query.trim()}
						onclick={() => { if (query.trim()) select(query.trim()); }}
					>
						Confirm
					</button>
				</div>
			{:else}
				<!-- Search -->
				<div class="relative border-b border-edge">
					<Search size={12} class="absolute top-1/2 left-2.5 -translate-y-1/2 text-fg-faint" />
					<input
						bind:this={inputEl}
						bind:value={query}
						type="text"
						placeholder="Search models..."
						class="w-full bg-transparent py-2 pr-2.5 pl-7 font-mono text-[12px] text-fg outline-none placeholder:text-fg-faint"
					/>
				</div>

				<!-- List -->
				<div class="max-h-56 overflow-y-auto">
					{#each filtered() as model, idx}
						{@const isSelected = model.name === value}
						{@const isHighlighted = highlightIndex === idx || isSelected}
						<!-- svelte-ignore a11y_click_events_have_key_events -->
						<!-- svelte-ignore a11y_no_static_element_interactions -->
						<div
							class="cursor-pointer px-3 py-1.5 transition-[background-color] duration-150 hover:bg-accent-primary/[0.03] {isHighlighted ? 'bg-accent-primary/[0.06]' : ''} {isSelected ? 'border-l-2 border-l-accent-primary pl-2.5' : ''}"
							onclick={() => select(model.name)}
						>
							<div class="flex items-center gap-2">
								<span class="min-w-0 truncate font-mono text-[12px] text-fg">{model.name}</span>
							</div>
							{#if model.description && !compact}
								<p class="truncate text-[11px] text-fg-faint">{model.description}</p>
							{/if}
						</div>
					{/each}

					{#if filtered().length === 0}
						<div class="px-3 py-3 text-center font-mono text-[12px] text-fg-faint">No models match</div>
					{/if}
				</div>

				<!-- Pinned footer: custom model entry point -->
				<!-- svelte-ignore a11y_click_events_have_key_events -->
				<!-- svelte-ignore a11y_no_static_element_interactions -->
				<div
					class="cursor-pointer border-t border-edge px-3 py-2 transition-[background-color] duration-150 hover:bg-accent-primary/[0.03] {highlightIndex === filtered().length ? 'bg-accent-primary/[0.06]' : ''}"
					onclick={(e) => { e.stopPropagation(); enterCustomMode(); }}
				>
					<span class="flex items-center gap-1.5 font-mono text-[12px] text-fg-faint">
						<Pencil size={11} />
						Enter custom model ID
					</span>
				</div>
			{/if}
		</div>
	{/if}
</div>
