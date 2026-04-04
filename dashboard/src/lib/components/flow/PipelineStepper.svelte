<script lang="ts">
	import SeedAvatar from '$lib/components/ui/SeedAvatar.svelte';
	import { CheckCircle } from 'lucide-svelte';

	let {
		agents,
		completedAgents,
		activeAgents,
		elapsed
	}: {
		agents: string[];
		completedAgents: string[];
		activeAgents: Set<string>;
		elapsed: number;
	} = $props();

	function agentState(name: string): 'active' | 'complete' | 'pending' {
		if (activeAgents.has(name)) return 'active';
		if (completedAgents.includes(name)) return 'complete';
		return 'pending';
	}

	const stepNum = $derived(completedAgents.length + 1);
</script>

<div class="flex items-center gap-1.5">
	<!-- Agent nodes -->
	{#each agents as name, i}
		{@const state = agentState(name)}
		<div class="flex items-center gap-1 {state === 'pending' ? 'opacity-30' : ''}">
			<div class="relative">
				<SeedAvatar seed={name} size={20} spinning={state === 'active'} />
				{#if state === 'complete'}
					<CheckCircle
						size={9}
						class="absolute -bottom-0.5 -right-0.5 rounded-full bg-surface-0 text-ok"
					/>
				{/if}
			</div>
			<span
				class="font-mono text-[10px] {state === 'active'
					? 'text-accent-primary'
					: 'text-fg-faint'}"
			>
				{name}
			</span>
		</div>

		<!-- Connector dash -->
		{#if i < agents.length - 1}
			<div class="h-px w-3 bg-fg-faint/20"></div>
		{/if}
	{/each}

	<!-- Step counter + elapsed -->
	<span
		class="ml-2 font-mono text-[11px] text-fg-faint"
		style="font-variant-numeric: tabular-nums"
	>
		{stepNum}/{agents.length} &middot; {elapsed}s
	</span>
</div>
