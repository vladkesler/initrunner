<script lang="ts">
	import { page } from '$app/state';
	import { onMount } from 'svelte';
	import { getAgentDetail, getAgentYaml } from '$lib/api/agents';
	import type { AgentDetail } from '$lib/api/types';
	import { Skeleton } from '$lib/components/ui/skeleton';
	import ConfigPanel from '$lib/components/agents/ConfigPanel.svelte';
	import RunPanel from '$lib/components/runs/RunPanel.svelte';
	import { ArrowLeft, ChevronRight } from 'lucide-svelte';

	let detail: AgentDetail | null = $state(null);
	let yaml = $state('');
	let loading = $state(true);
	let configOpen = $state(false);

	const agentId = $derived(page.params.id ?? '');

	onMount(async () => {
		try {
			const [d, y] = await Promise.all([getAgentDetail(agentId), getAgentYaml(agentId)]);
			detail = d;
			yaml = y.yaml;
		} catch {
			// not found
		} finally {
			loading = false;
		}
	});
</script>

<div class="flex h-full flex-col gap-5">
	<!-- Back link -->
	<a
		href="/agents"
		class="inline-flex items-center gap-1.5 text-[13px] text-fg-faint transition-[color] duration-150 hover:text-fg-muted"
	>
		<ArrowLeft size={14} />
		Agents
	</a>

	{#if loading}
		<Skeleton class="h-6 w-48 bg-surface-1" />
		<Skeleton class="h-64 bg-surface-1" />
	{:else if detail}
		<!-- Header -->
		<div>
			<div class="flex items-center gap-3">
				<h1 class="text-xl font-semibold tracking-[-0.02em] text-fg" style="text-wrap: balance">{detail.name}</h1>
				{#if detail.model.provider}
					<span
						class="border border-edge bg-surface-1 px-2 py-0.5 font-mono text-[12px] text-fg-faint"
					>
						{detail.model.provider}/{detail.model.name}
					</span>
				{/if}
			</div>
			{#if detail.description}
				<p class="mt-1 text-[13px] text-fg-muted">{detail.description}</p>
			{/if}
		</div>

		<!-- Error block -->
		{#if detail.error}
			<div class="border-l-2 border-l-fail bg-fail/5 px-3 py-2">
				<p class="font-mono text-sm text-fail">{detail.error}</p>
			</div>
		{/if}

		<!-- Split layout -->
		<div class="flex min-h-0 flex-1 flex-col gap-5 lg:flex-row lg:gap-0">
			<!-- Config panel: sidebar on lg, collapsible on mobile -->
			<div class="shrink-0 lg:w-[360px] lg:overflow-y-auto lg:border-r lg:border-edge lg:bg-surface-1 lg:pr-5">
				<!-- Mobile toggle -->
				<button
					class="flex w-full items-center gap-1.5 border-b border-edge pb-3 lg:hidden"
					onclick={() => (configOpen = !configOpen)}
					aria-expanded={configOpen}
				>
					<ChevronRight
						size={12}
						class="shrink-0 text-fg-faint transition-transform duration-150 {configOpen ? 'rotate-90' : ''}"
					/>
					<span class="font-mono text-[12px] font-medium uppercase tracking-[0.1em] text-fg-faint">
						Configuration
					</span>
				</button>

				<!-- Desktop: always visible. Mobile: toggled -->
				<div class="hidden lg:block">
					<ConfigPanel {detail} {yaml} />
				</div>
				{#if configOpen}
					<div class="pt-3 lg:hidden">
						<ConfigPanel {detail} {yaml} />
					</div>
				{/if}
			</div>

			<!-- Run panel -->
			<div class="flex min-w-0 flex-1 flex-col lg:pl-5">
				<RunPanel agentId={agentId} />
			</div>
		</div>
	{:else}
		<p class="text-fg-faint">Agent not found</p>
	{/if}
</div>
