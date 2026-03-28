<script lang="ts">
	import type { NodeProps } from '@xyflow/svelte';
	import type { AgentSummary } from '$lib/api/types';
	import { goto } from '$app/navigation';
	import CapabilityGlyph from './CapabilityGlyph.svelte';
	import { Wrench, Zap, BookOpen, Plug, Sparkles, AlertTriangle } from 'lucide-svelte';

	let { data, selected, dragging }: NodeProps<{ agent: AgentSummary }> = $props();

	const agent = $derived(data.agent);

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

	function handleClick() {
		if (!dragging) goto(`/agents/${agent.id}`);
	}
</script>

<div
	class="w-[240px] cursor-pointer bg-surface-1 p-3 transition-[border-color,box-shadow] duration-200
		{hasError ? 'card-surface-error' : 'card-surface'}
		{isRich && !hasError ? 'glow-lime-subtle' : ''}
		{selected ? 'glow-lime' : ''}"
	onclick={handleClick}
	role="link"
	tabindex="0"
	onkeydown={(e) => { if (e.key === 'Enter') handleClick(); }}
>
	<!-- Name row -->
	<div class="flex items-center gap-2">
		{#if heroIcon}
			{@const HeroIcon = heroIcon}
			<HeroIcon size={13} strokeWidth={1.5} class="shrink-0 text-fg-faint" />
		{/if}
		<span class="min-w-0 truncate text-[13px] font-semibold text-fg">{agent.name}</span>
		{#if hasError}
			<AlertTriangle size={11} class="shrink-0 text-fail" />
		{/if}
		<div class="ml-auto flex shrink-0 items-center gap-1">
			{#if agent.features.includes('tool_search')}
				<span class="rounded-full border border-accent-secondary/20 bg-accent-secondary/10 px-1 py-0.5 font-mono text-[9px] text-accent-secondary">search</span>
			{/if}
			<CapabilityGlyph features={agent.features} />
		</div>
	</div>

	<!-- Model -->
	<p class="mt-1 truncate font-mono text-[11px] text-fg-faint">
		{agent.provider ? `${agent.provider}/${agent.model}` : 'no model'}
	</p>

	<!-- Description -->
	{#if agent.description}
		<p class="mt-1.5 line-clamp-2 text-[11px] leading-[1.4] text-fg-muted">{agent.description}</p>
	{/if}
</div>
