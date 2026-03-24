<script lang="ts">
	import { ChevronRight } from 'lucide-svelte';
	import type { Snippet } from 'svelte';

	let {
		title,
		count,
		defaultOpen = true,
		children
	}: {
		title: string;
		count?: number;
		defaultOpen?: boolean;
		children: Snippet;
	} = $props();

	// svelte-ignore state_referenced_locally
	let expanded = $state(defaultOpen);
</script>

<div>
	<button
		class="flex w-full items-center gap-1.5 py-1.5 text-left"
		onclick={() => (expanded = !expanded)}
		aria-expanded={expanded}
	>
		<ChevronRight
			size={12}
			class="shrink-0 text-fg-faint transition-transform duration-150 {expanded ? 'rotate-90' : ''}"
		/>
		<span class="font-mono text-[12px] font-medium uppercase tracking-[0.1em] text-fg-faint">
			{title}
		</span>
		{#if count !== undefined}
			<span class="font-mono text-[12px] text-fg-faint">({count})</span>
		{/if}
	</button>
	{#if expanded}
		<div class="pb-3 pl-[18px] pt-1">
			{@render children()}
		</div>
	{/if}
</div>
