<script lang="ts">
	import type { AgentSummary } from '$lib/api/types';
	import { Layers, Wrench, Zap, BookOpen, Plug, Sparkles, Brain, Gem, AlertTriangle } from 'lucide-svelte';

	let {
		agents,
		activeFilter = 'all',
		onFilterChange,
	}: {
		agents: AgentSummary[];
		activeFilter: string;
		onFilterChange: (filter: string) => void;
	} = $props();

	const categories = [
		{ key: 'all', label: 'All', icon: Layers, accent: 'primary' as const },
		{ key: 'equipped', label: 'Equipped', icon: Wrench, accent: 'primary' as const },
		{ key: 'reactive', label: 'Reactive', icon: Zap, accent: 'secondary' as const },
		{ key: 'intelligence', label: 'Intelligence', icon: BookOpen, accent: 'primary' as const },
		{ key: 'connected', label: 'Connected', icon: Plug, accent: 'secondary' as const },
		{ key: 'skilled', label: 'Skilled', icon: Sparkles, accent: 'primary' as const },
		{ key: 'cognitive', label: 'Cognitive', icon: Brain, accent: 'primary' as const },
		{ key: 'enhanced', label: 'Enhanced', icon: Gem, accent: 'secondary' as const },
		{ key: 'errored', label: 'Errored', icon: AlertTriangle, accent: 'fail' as const },
	] as const;

	function matchesFilter(agent: AgentSummary, key: string): boolean {
		switch (key) {
			case 'all': return true;
			case 'equipped': return agent.features.includes('tools');
			case 'reactive': return agent.features.includes('triggers');
			case 'intelligence': return agent.features.includes('ingest') || agent.features.includes('memory');
			case 'connected': return agent.features.includes('sinks');
			case 'skilled': return agent.features.includes('skills');
			case 'cognitive': return agent.features.includes('reasoning') || agent.features.includes('autonomy');
			case 'enhanced': return agent.features.includes('capabilities');
			case 'errored': return agent.error !== null;
			default: return true;
		}
	}

	const counts = $derived(
		Object.fromEntries(categories.map((c) => [c.key, agents.filter((a) => matchesFilter(a, c.key)).length]))
	);
</script>

<div class="flex flex-wrap gap-1.5" role="toolbar" aria-label="Filter agents by capability">
	{#each categories as cat}
		{@const count = counts[cat.key] ?? 0}
		{#if cat.key !== 'errored' || count > 0}
			{@const isActive = activeFilter === cat.key}
			{@const isFail = cat.accent === 'fail'}
			<button
				class="flex shrink-0 items-center gap-1.5 rounded-full border px-3 py-1.5 font-mono text-[12px] transition-[color,background-color,border-color] duration-150
					{isActive
						? isFail
							? 'border-fail/30 bg-fail/10 text-fail'
							: 'border-accent-primary-dim/40 bg-accent-primary-wash text-fg'
						: 'border-edge bg-transparent text-fg-faint hover:text-fg-muted'}"
				onclick={() => onFilterChange(cat.key)}
				aria-pressed={isActive}
			>
				<cat.icon size={14} strokeWidth={1.5} />
				<span>{cat.label}</span>
				<span class="opacity-40">({count})</span>
			</button>
		{/if}
	{/each}
</div>
