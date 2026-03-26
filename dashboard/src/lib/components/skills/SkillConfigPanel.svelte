<script lang="ts">
	import type { SkillDetail } from '$lib/api/types';
	import ConfigSection from '$lib/components/agents/ConfigSection.svelte';
	import { CheckCircle, XCircle } from 'lucide-svelte';

	let { detail }: { detail: SkillDetail } = $props();

	let showFullPrompt = $state(false);

	const hasMetadata = $derived(
		detail.license ||
			detail.compatibility ||
			Object.keys(detail.metadata).length > 0
	);
</script>

<div class="space-y-1">
	<!-- Description (non-collapsible) -->
	<div class="pb-3">
		<h3
			class="mb-2 font-mono text-[12px] font-medium uppercase tracking-[0.1em] text-fg-faint"
		>
			Description
		</h3>
		<p class="pl-0.5 text-[13px] text-fg-muted">
			{detail.description || '(no description)'}
		</p>
	</div>

	<!-- Tools -->
	{#if detail.tools.length > 0}
		<ConfigSection title="Tools" count={detail.tools.length}>
			<div class="space-y-1">
				{#each detail.tools as tool}
					<div class="font-mono text-[13px]">
						<span class="text-accent-primary">{tool.type}</span>
						<span class="ml-1.5 text-fg-muted">{tool.summary}</span>
					</div>
				{/each}
			</div>
		</ConfigSection>
	{/if}

	<!-- Requirements -->
	{#if detail.requirements.length > 0}
		<ConfigSection title="Requirements" count={detail.requirements.length}>
			<div class="space-y-1">
				{#each detail.requirements as req}
					<div class="flex items-center gap-2 font-mono text-[13px]">
						{#if req.met}
							<CheckCircle size={13} class="shrink-0 text-ok" />
						{:else}
							<XCircle size={13} class="shrink-0 text-fail" />
						{/if}
						<span class="text-fg-muted">{req.kind}:{req.name}</span>
						{#if !req.met && req.detail}
							<span class="text-fg-faint">({req.detail})</span>
						{/if}
					</div>
				{/each}
			</div>
		</ConfigSection>
	{/if}

	<!-- Prompt -->
	{#if detail.prompt}
		<ConfigSection title="Prompt" defaultOpen={false}>
			<pre
				class="whitespace-pre-wrap font-mono text-[13px] leading-relaxed text-fg-muted"
			>{showFullPrompt ? detail.prompt : detail.prompt_preview}</pre>
			{#if detail.prompt.length > 500}
				<button
					class="mt-2 font-mono text-[12px] text-accent-primary/60 transition-[color] duration-150 hover:text-accent-primary"
					onclick={() => (showFullPrompt = !showFullPrompt)}
				>
					{showFullPrompt ? 'Show less' : 'Show full'}
				</button>
			{/if}
		</ConfigSection>
	{/if}

	<!-- Metadata -->
	{#if hasMetadata}
		<ConfigSection title="Metadata" defaultOpen={false}>
			<div class="space-y-1 font-mono text-[13px]">
				{#if detail.license}
					<div>
						<span class="text-fg-faint">license</span>
						<span class="ml-1 text-fg-muted">{detail.license}</span>
					</div>
				{/if}
				{#if detail.compatibility}
					<div>
						<span class="text-fg-faint">compatibility</span>
						<span class="ml-1 text-fg-muted">{detail.compatibility}</span>
					</div>
				{/if}
				{#each Object.entries(detail.metadata) as [key, value]}
					<div>
						<span class="text-fg-faint">{key}</span>
						<span class="ml-1 text-fg-muted">{value}</span>
					</div>
				{/each}
				<div>
					<span class="text-fg-faint">path</span>
					<span class="ml-1 text-fg-muted">{detail.path}</span>
				</div>
			</div>
		</ConfigSection>
	{/if}

	<!-- Used By -->
	{#if detail.used_by_agents.length > 0}
		<ConfigSection title="Used By" count={detail.used_by_agents.length}>
			<div class="flex flex-wrap gap-2">
				{#each detail.used_by_agents as ref}
					<a
						href="/agents/{ref.id}"
						class="font-mono text-[13px] text-accent-primary transition-[color] duration-150 hover:underline"
					>
						{ref.name}
					</a>
				{/each}
			</div>
		</ConfigSection>
	{/if}
</div>
