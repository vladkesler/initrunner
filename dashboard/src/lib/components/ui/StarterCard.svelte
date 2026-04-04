<script lang="ts">
	import type { StarterInfo } from '$lib/api/builder';

	interface Props {
		starter: StarterInfo;
		index: number;
	}

	let { starter, index }: Props = $props();

	const href = $derived(
		starter.kind === 'Team'
			? `/teams/new?starter=${starter.slug}`
			: starter.kind === 'Flow'
				? `/flows/new?starter=${starter.slug}`
				: `/agents/new?starter=${starter.slug}`
	);
</script>

<a
	href={href}
	class="group card-surface relative block overflow-hidden bg-surface-1 p-4 transition-[background-color] duration-150 animate-fade-in-up hover:bg-surface-2"
	style="animation-delay: {index * 60}ms"
>
	<!-- Hover gradient wash -->
	<div
		class="pointer-events-none absolute inset-0 bg-gradient-to-br from-accent-primary/[0.04] via-transparent to-transparent opacity-0 transition-[opacity] duration-150 group-hover:opacity-100"
	></div>

	<div class="relative">
		<div class="font-mono text-[13px] font-semibold text-fg transition-[color] duration-150 group-hover:text-accent-primary">
			{starter.name}
		</div>
		<div class="mt-1 line-clamp-2 text-[13px] text-fg-muted">
			{starter.description}
		</div>
		{#if starter.features.length > 0}
			<div class="mt-3 flex flex-wrap gap-1.5">
				{#each starter.features as feature}
					<span class="rounded-full border border-edge bg-surface-2 px-2 py-0.5 font-mono text-[12px] text-fg-faint">
						{feature}
					</span>
				{/each}
			</div>
		{/if}
	</div>
</a>
