<script lang="ts">
	import type { SkillSummary } from '$lib/api/types';
	import ScopeBadge from './ScopeBadge.svelte';
	import { Sparkles, AlertTriangle } from 'lucide-svelte';

	let { skill }: { skill: SkillSummary } = $props();

	const hasError = $derived(skill.error !== null);
	const isRich = $derived(skill.tool_count >= 3);

	// Show up to 3 tool types as pills
	// SkillSummary doesn't carry tool names, so show count
</script>

<a
	href="/skills/{skill.id}"
	class="group relative block overflow-hidden bg-surface-1 p-4 transition-[background-color,border-color] duration-200 hover:bg-surface-2
		{hasError ? 'card-surface-error' : 'card-surface'}"
>
	<div class="relative min-w-0">
		<!-- Name row -->
		<div class="flex items-center gap-2">
			<Sparkles size={14} strokeWidth={1.5} class="shrink-0 text-fg-faint" />
			<h3 class="truncate text-[14px] font-semibold text-fg">{skill.name}</h3>
			{#if hasError}
				<AlertTriangle size={12} class="shrink-0 text-fail" />
			{/if}
			<div class="ml-auto shrink-0">
				<ScopeBadge scope={skill.scope} size="sm" />
			</div>
		</div>

		<!-- Description -->
		{#if skill.description}
			<p class="mt-2 line-clamp-2 text-[13px] text-fg-muted">{skill.description}</p>
		{/if}

		<!-- Type indicator -->
		<div class="mt-3 flex flex-wrap items-center gap-1.5">
			{#if skill.has_tools}
				<span
					class="rounded-full border border-edge bg-surface-0 px-2 py-0.5 font-mono text-[11px] text-accent-primary"
				>
					{skill.tool_count} tool{skill.tool_count !== 1 ? 's' : ''}
				</span>
			{:else}
				<span
					class="rounded-full border border-edge bg-surface-0 px-2 py-0.5 font-mono text-[11px] text-fg-faint"
				>
					methodology
				</span>
			{/if}

			{#if skill.requirement_count > 0}
				<span class="ml-auto font-mono text-[11px] {skill.requirements_met ? 'text-fg-faint' : 'text-warn'}">
					{#if skill.requirements_met}
						{skill.requirement_count}/{skill.requirement_count} met
					{:else}
						reqs unmet
					{/if}
				</span>
			{/if}
		</div>
	</div>
</a>
