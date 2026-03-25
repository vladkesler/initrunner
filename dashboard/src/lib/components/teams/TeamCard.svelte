<script lang="ts">
	import type { TeamSummary } from '$lib/api/types';
	import { goto } from '$app/navigation';
	import { Database, FileText, Trash2 } from 'lucide-svelte';

	let { team, idx, onDelete }: { team: TeamSummary; idx: number; onDelete?: (team: TeamSummary) => void } = $props();
</script>

<div
	class="group cursor-pointer border bg-surface-1 p-4 transition-[border-color,background-color,box-shadow] duration-150 hover:border-accent-primary/20 hover:bg-gradient-to-br hover:from-accent-primary/[0.03] hover:to-transparent {team.error ? 'card-surface-error' : 'card-surface'}"
	style="animation: fadeIn 300ms ease-out {idx * 50}ms both"
	role="link"
	tabindex="0"
	onclick={() => goto(`/teams/${team.id}`)}
	onkeydown={(e) => { if (e.key === 'Enter') goto(`/teams/${team.id}`); }}
>
	<div class="flex items-start justify-between gap-2">
		<h3 class="font-mono text-[13px] font-medium text-fg">{team.name}</h3>
		<div class="flex shrink-0 items-center gap-1.5">
			<span class="rounded-full border border-accent-primary/20 bg-accent-primary/10 px-2 py-0.5 font-mono text-[11px] text-accent-primary">
				{team.strategy}
			</span>
			{#if team.has_model_overrides}
				<span class="rounded-full border border-edge bg-surface-2 px-2 py-0.5 font-mono text-[11px] text-fg-faint">
					mixed models
				</span>
			{/if}
			{#if onDelete}
				<button
					class="flex items-center justify-center rounded-md p-1 text-fg-faint opacity-0 transition-all duration-150 hover:bg-destructive/10 hover:text-destructive group-hover:opacity-100"
					onclick={(e) => { e.stopPropagation(); onDelete(team); }}
					aria-label="Delete {team.name}"
				>
					<Trash2 size={13} />
				</button>
			{/if}
		</div>
	</div>

	<div class="mt-1 font-mono text-[11px] text-fg-faint">
		{team.provider}/{team.model}
	</div>

	{#if team.error}
		<p class="mt-2 border-l-2 border-fail/40 pl-2 text-[11px] text-fail">{team.error}</p>
	{:else}
		{#if team.description}
			<p class="mt-1.5 line-clamp-2 text-[12px] text-fg-faint">{team.description}</p>
		{/if}

		<div class="mt-2 flex flex-wrap gap-1">
			{#each team.persona_names.slice(0, 5) as persona}
				<span class="rounded-full border border-edge bg-surface-2 px-2 py-0.5 font-mono text-[11px] text-fg-faint">
					{persona}
				</span>
			{/each}
			{#if team.persona_names.length > 5}
				<span class="rounded-full border border-edge bg-surface-2 px-2 py-0.5 font-mono text-[11px] text-fg-faint">
					+{team.persona_names.length - 5}
				</span>
			{/if}
		</div>

		{#if team.features.includes('shared_memory') || team.features.includes('shared_documents')}
			<div class="mt-2 flex flex-wrap gap-1.5">
				{#if team.features.includes('shared_memory')}
					<span class="flex items-center gap-1 rounded-full border border-edge bg-surface-2 px-2 py-0.5 font-mono text-[11px] text-fg-faint">
						<Database size={10} />
						memory
					</span>
				{/if}
				{#if team.features.includes('shared_documents')}
					<span class="flex items-center gap-1 rounded-full border border-edge bg-surface-2 px-2 py-0.5 font-mono text-[11px] text-fg-faint">
						<FileText size={10} />
						documents
					</span>
				{/if}
			</div>
		{/if}
	{/if}
</div>
