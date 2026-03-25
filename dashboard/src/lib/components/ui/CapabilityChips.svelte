<script lang="ts">
	import { Database, Brain, Zap, Workflow, Users, ExternalLink } from 'lucide-svelte';

	const chips = [
		{ label: 'RAG', icon: Database, href: 'https://www.initrunner.ai/docs/rag-quickstart', external: true },
		{ label: 'Memory', icon: Brain, href: 'https://www.initrunner.ai/docs/memory', external: true },
		{ label: 'Triggers', icon: Zap, href: 'https://www.initrunner.ai/docs/triggers', external: true },
		{ label: 'Compose', icon: Workflow, href: '/compose/new', external: false },
		{ label: 'Teams', icon: Users, href: '/teams/new', external: false },
	];
</script>

<div class="flex flex-wrap gap-2">
	{#each chips as chip}
		<a
			href={chip.href}
			target={chip.external ? '_blank' : undefined}
			rel={chip.external ? 'noopener' : undefined}
			class="inline-flex items-center gap-1.5 rounded-full border border-edge bg-surface-1 px-3 py-1.5 font-mono text-[12px] text-fg-faint transition-[color,background-color,border-color] duration-150 hover:border-accent-primary/20 hover:bg-surface-2 hover:text-fg-muted"
		>
			<chip.icon size={14} />
			{chip.label}
			{#if chip.external}
				<ExternalLink size={10} />
			{/if}
		</a>
	{/each}
</div>
