<script lang="ts">
	import { page } from '$app/state';
	import { onMount } from 'svelte';
	import { getAgent, getAgentYaml } from '$lib/api/agents';
	import type { AgentSummary } from '$lib/api/types';
	import * as Tabs from '$lib/components/ui/tabs';
	import { Skeleton } from '$lib/components/ui/skeleton';
	import RunPanel from '$lib/components/runs/RunPanel.svelte';
	import { ArrowLeft, Copy, Check } from 'lucide-svelte';

	let agent: AgentSummary | null = $state(null);
	let yaml = $state('');
	let yamlPath = $state('');
	let loading = $state(true);
	let activeTab = $state('overview');
	let copied = $state(false);

	const agentId = $derived(page.params.id);

	onMount(async () => {
		try {
			const [a, y] = await Promise.all([getAgent(agentId), getAgentYaml(agentId)]);
			agent = a;
			yaml = y.yaml;
			yamlPath = y.path;
		} catch {
			// not found
		} finally {
			loading = false;
		}
	});

	async function copyYaml() {
		await navigator.clipboard.writeText(yaml);
		copied = true;
		setTimeout(() => (copied = false), 2000);
	}
</script>

<div class="space-y-5">
	<!-- Back link -->
	<a href="/agents" class="inline-flex items-center gap-1.5 text-[13px] text-fg-faint transition-[color] duration-150 hover:text-fg-muted">
		<ArrowLeft size={14} />
		Agents
	</a>

	{#if loading}
		<Skeleton class="h-6 w-48 rounded-sm bg-surface-1" />
		<Skeleton class="h-64 rounded-sm bg-surface-1" />
	{:else if agent}
		<!-- Header -->
		<div>
			<div class="flex items-center gap-3">
				<h1 class="text-lg font-medium text-fg" style="text-wrap: balance">{agent.name}</h1>
				{#if agent.provider}
					<span class="rounded-sm border border-edge bg-surface-1 px-2 py-0.5 font-mono text-[11px] text-fg-faint">
						{agent.provider}/{agent.model}
					</span>
				{/if}
			</div>
			{#if agent.description}
				<p class="mt-1 text-[13px] text-fg-muted">{agent.description}</p>
			{/if}
		</div>

		<!-- Error block -->
		{#if agent.error}
			<div class="rounded-sm border-l-2 border-l-fail bg-fail/5 px-3 py-2">
				<p class="font-mono text-xs text-fail">{agent.error}</p>
			</div>
		{/if}

		<!-- Tabs -->
		<Tabs.Root bind:value={activeTab}>
			<Tabs.List class="border-b border-edge bg-transparent">
				<Tabs.Trigger
					value="overview"
					class="text-[13px] font-medium data-[state=active]:border-b-2 data-[state=active]:border-b-orange data-[state=active]:text-fg data-[state=inactive]:text-fg-faint data-[state=inactive]:hover:text-fg-muted"
				>
					Overview
				</Tabs.Trigger>
				<Tabs.Trigger
					value="yaml"
					class="text-[13px] font-medium data-[state=active]:border-b-2 data-[state=active]:border-b-orange data-[state=active]:text-fg data-[state=inactive]:text-fg-faint data-[state=inactive]:hover:text-fg-muted"
				>
					YAML
				</Tabs.Trigger>
				<Tabs.Trigger
					value="run"
					class="text-[13px] font-medium data-[state=active]:border-b-2 data-[state=active]:border-b-orange data-[state=active]:text-fg data-[state=inactive]:text-fg-faint data-[state=inactive]:hover:text-fg-muted"
				>
					Run
				</Tabs.Trigger>
			</Tabs.List>

			<Tabs.Content value="overview" class="pt-5">
				<div class="space-y-5">
					{#if agent.features.length > 0}
						<div>
							<h3 class="mb-2 font-mono text-[11px] font-medium uppercase tracking-[0.08em] text-fg-faint">Features</h3>
							<div class="flex flex-wrap gap-1.5">
								{#each agent.features as feature}
									<span class="rounded-sm bg-surface-2 px-2 py-0.5 font-mono text-[11px] text-fg-muted">{feature}</span>
								{/each}
							</div>
						</div>
					{/if}

					{#if agent.tags.length > 0}
						<div>
							<h3 class="mb-2 font-mono text-[11px] font-medium uppercase tracking-[0.08em] text-fg-faint">Tags</h3>
							<div class="flex flex-wrap gap-1.5">
								{#each agent.tags as tag}
									<span class="rounded-sm bg-surface-2 px-2 py-0.5 font-mono text-[11px] text-fg-muted">{tag}</span>
								{/each}
							</div>
						</div>
					{/if}

					<div>
						<h3 class="mb-1 font-mono text-[11px] font-medium uppercase tracking-[0.08em] text-fg-faint">Path</h3>
						<p class="font-mono text-[12px] text-fg-muted">{agent.path}</p>
					</div>
				</div>
			</Tabs.Content>

			<Tabs.Content value="yaml" class="pt-5">
				<div class="overflow-hidden rounded-sm border border-edge">
					<div class="flex items-center justify-between border-b border-edge bg-surface-1 px-3 py-1.5">
						<span class="font-mono text-[11px] text-fg-faint">{yamlPath}</span>
						<button
							class="flex items-center gap-1.5 text-[11px] text-fg-faint transition-[color] duration-150 hover:text-fg-muted"
							onclick={copyYaml}
							aria-label="Copy YAML"
						>
							{#if copied}
								<Check size={14} class="text-ok" />
								<span class="text-ok">Copied</span>
							{:else}
								<Copy size={14} />
								<span>Copy</span>
							{/if}
						</button>
					</div>
					<pre class="overflow-auto bg-surface-0 p-4 font-mono text-[13px] leading-relaxed text-fg-muted">{yaml}</pre>
				</div>
			</Tabs.Content>

			<Tabs.Content value="run" class="pt-5">
				<RunPanel {agentId} />
			</Tabs.Content>
		</Tabs.Root>
	{:else}
		<p class="text-fg-faint">Agent not found</p>
	{/if}
</div>
