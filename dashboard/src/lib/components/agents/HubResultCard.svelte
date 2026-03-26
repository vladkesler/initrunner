<script lang="ts">
	import type { HubSearchResult } from '$lib/api/builder';
	import { Download } from 'lucide-svelte';

	let {
		result,
		selected,
		animationDelay,
		onSelect
	}: {
		result: HubSearchResult;
		selected: boolean;
		animationDelay?: string;
		onSelect: (result: HubSearchResult) => void;
	} = $props();
</script>

<button
	class="border p-3 text-left transition-[background-color,border-color] duration-150 hover:bg-surface-2"
	class:animate-fade-in-up={animationDelay !== undefined}
	class:border-accent-primary={selected}
	class:bg-surface-2={selected}
	class:bg-surface-1={!selected}
	class:border-edge={!selected}
	style={animationDelay !== undefined ? `animation-delay: ${animationDelay}` : undefined}
	aria-pressed={selected}
	onclick={() => onSelect(result)}
>
	<div class="font-mono text-[13px] font-medium text-fg">
		{result.owner}/{result.name}
	</div>
	<div class="mt-1 line-clamp-2 text-[13px] text-fg-faint">
		{result.description}
	</div>
	<div class="mt-2 flex flex-wrap items-center gap-2">
		{#if result.latest_version}
			<span class="rounded-full bg-surface-3 px-2 py-0.5 font-mono text-[11px] text-fg-muted">
				v{result.latest_version}
			</span>
		{/if}
		<span class="flex items-center gap-1 font-mono text-[11px] text-fg-faint">
			<Download size={10} />
			{result.downloads}
		</span>
		{#each result.tags.slice(0, 3) as tag}
			<span class="rounded-full border border-edge px-2 py-0.5 font-mono text-[11px] text-fg-faint">
				{tag}
			</span>
		{/each}
	</div>
</button>
