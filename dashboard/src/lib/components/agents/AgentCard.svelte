<script lang="ts">
	import type { AgentSummary } from '$lib/api/types';
	import CapabilityGlyph from './CapabilityGlyph.svelte';
	import { Wrench, Zap, BookOpen, Plug, Sparkles, AlertTriangle } from 'lucide-svelte';

	let { agent }: { agent: AgentSummary } = $props();

	const heroIcon = $derived.by(() => {
		if (agent.features.includes('triggers')) return Zap;
		if (agent.features.includes('tools')) return Wrench;
		if (agent.features.includes('ingest') || agent.features.includes('memory')) return BookOpen;
		if (agent.features.includes('sinks')) return Plug;
		if (agent.features.includes('skills')) return Sparkles;
		return null;
	});

	const hasError = $derived(agent.error !== null);
	const isRich = $derived(agent.features.length >= 4);
</script>

<a
	href="/agents/{agent.id}"
	class="group relative block overflow-hidden bg-surface-1 p-4 transition-[background-color,border-color] duration-200 hover:bg-surface-2
		{hasError ? 'card-surface-error' : 'card-surface'}
		{isRich && !hasError ? 'glow-lime-subtle' : ''}"
>
	<!-- Hover gradient wash -->
	<div class="pointer-events-none absolute inset-0 bg-gradient-to-br from-accent-primary/[0.04] via-transparent to-transparent opacity-0 transition-opacity duration-200 group-hover:opacity-100"></div>

	<div class="relative min-w-0">
		<!-- Name row: hero icon + name + error indicator -->
		<div class="flex items-center gap-2">
			{#if heroIcon}
				{@const HeroIcon = heroIcon}
				<HeroIcon size={14} strokeWidth={1.5} class="shrink-0 text-fg-faint" />
			{/if}
			<h3 class="truncate text-[14px] font-semibold text-fg">{agent.name}</h3>
			{#if hasError}
				<AlertTriangle size={12} class="shrink-0 text-fail" />
			{/if}
		</div>

		<!-- Model -->
		<p class="mt-1 truncate font-mono text-[13px] text-fg-faint">
			{#if agent.provider}
				{agent.provider}/{agent.model}
			{:else}
				<span class="rounded-full border border-edge bg-surface-2 px-1.5 py-0.5 font-mono text-[10px] text-fg-faint">auto</span>
			{/if}
		</p>

		<!-- Description -->
		{#if agent.description}
			<p class="mt-2 line-clamp-2 text-[13px] text-fg-muted">{agent.description}</p>
		{/if}

		<!-- Bottom row: glyph + badges + first tag -->
		<div class="mt-3 flex items-center justify-between">
			<div class="flex items-center gap-1.5">
				<CapabilityGlyph features={agent.features} />
				{#if agent.features.includes('tool_search')}
					<span class="rounded-full border border-accent-secondary/20 bg-accent-secondary/10 px-1.5 py-0.5 font-mono text-[10px] text-accent-secondary">search</span>
				{/if}
			</div>
			{#if agent.tags.length > 0}
				<span class="max-w-[120px] truncate font-mono text-[12px] text-fg-faint">
					{agent.tags[0]}{#if agent.tags.length > 1}<span class="ml-1 text-fg-faint/50">+{agent.tags.length - 1}</span>{/if}
				</span>
			{/if}
		</div>
	</div>
</a>
