<script lang="ts">
	import type { NodeProps } from '@xyflow/svelte';
	import type { AgentSummary } from '$lib/api/types';
	import { goto } from '$app/navigation';
	import CapabilityGlyph from './CapabilityGlyph.svelte';
	import { Play, Wrench, Zap, BookOpen, Plug, Sparkles, AlertTriangle } from 'lucide-svelte';

	let { data, selected, dragging }: NodeProps<{ agent: AgentSummary; onRun?: (agent: AgentSummary) => void }> = $props();

	const agent = $derived(data.agent);
	const onRun = $derived(data.onRun);

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

	function handleRun(e: MouseEvent) {
		e.stopPropagation();
		onRun?.(agent);
	}
</script>

<div
	class="group w-[240px] cursor-pointer bg-surface-1 p-3 transition-[border-color,box-shadow] duration-200
		{hasError ? 'card-surface-error' : 'card-surface'}
		{selected ? 'active-border' : ''}"
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
			{#if onRun}
				<button
					class="flex items-center justify-center rounded-[2px] p-0.5 text-fg-faint opacity-0 transition-all duration-150 hover:bg-accent-primary/10 hover:text-accent-primary group-hover:opacity-100"
					onclick={handleRun}
					aria-label="Run {agent.name}"
				>
					<Play size={12} />
				</button>
			{/if}
			{#if agent.features.includes('tool_search')}
				<span class="rounded-full border border-accent-secondary/20 bg-accent-secondary/10 px-1 py-0.5 font-mono text-[9px] text-accent-secondary">search</span>
			{/if}
			<CapabilityGlyph features={agent.features} />
		</div>
	</div>

	<!-- Model -->
	<p class="mt-1 truncate font-mono text-[11px] text-fg-faint">
		{#if agent.provider}
			{agent.provider}/{agent.model}
		{:else}
			<span class="rounded-full border border-edge bg-surface-2 px-1 py-0.5 font-mono text-[9px] text-fg-faint">auto</span>
		{/if}
	</p>

	<!-- Description -->
	{#if agent.description}
		<p class="mt-1.5 line-clamp-2 text-[11px] leading-[1.4] text-fg-muted">{agent.description}</p>
	{/if}
</div>
