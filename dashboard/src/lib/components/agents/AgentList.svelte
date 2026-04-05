<script lang="ts">
	import type { AgentSummary } from '$lib/api/types';
	import { goto } from '$app/navigation';
	import { Play, Trash2 } from 'lucide-svelte';
	import CapabilityGlyph from './CapabilityGlyph.svelte';

	let { agents, onDelete, onRun }: { agents: AgentSummary[]; onDelete?: (agent: AgentSummary) => void; onRun?: (agent: AgentSummary) => void } = $props();
</script>

{#if agents.length === 0}
	<div class="py-16 text-center">
		<p class="text-[13px] text-fg-faint">No agents found</p>
		<p class="mt-1 text-[13px] text-fg-faint">
			Create a <code class="font-mono">role.yaml</code> file to get started
		</p>
	</div>
{:else}
	<table class="w-full">
		<thead>
			<tr class="border-b border-edge bg-surface-05">
				<th class="w-8 px-3 py-2"></th>
				<th class="section-label px-3 py-2 text-left">Name</th>
				<th class="section-label hidden px-3 py-2 text-left md:table-cell">Description</th>
				<th class="section-label px-3 py-2 text-left">Model</th>
				<th class="section-label w-20 px-3 py-2 text-right">Capabilities</th>
				{#if onRun}<th class="w-10 px-2 py-2"></th>{/if}
				{#if onDelete}<th class="w-10 px-2 py-2"></th>{/if}
			</tr>
		</thead>
			<tbody>
				{#each agents as agent (agent.id)}
					<tr
						class="group cursor-pointer border-b border-edge-subtle transition-[background-color] duration-150 hover:bg-surface-1 {agent.error ? 'border-l-2 border-l-fail' : ''}"
						onclick={() => goto(`/agents/${agent.id}`)}
						onkeydown={(e) => { if (e.key === 'Enter') goto(`/agents/${agent.id}`); }}
						tabindex="0"
						role="link"
					>
						<td class="w-8 px-3 py-2">
							{#if agent.error}
								<span class="status-dot bg-fail"></span>
							{:else}
								<span class="status-dot bg-ok"></span>
							{/if}
						</td>
						<td class="px-3 py-2">
							<a href="/agents/{agent.id}" class="text-[13px] font-medium text-fg transition-[color] duration-150 hover:text-fg">{agent.name}</a>
						</td>
						<td class="hidden max-w-xs truncate px-3 py-2 text-[13px] text-fg-muted md:table-cell">
							{agent.description || '\u2014'}
						</td>
						<td class="px-3 py-2 font-mono text-[13px] text-fg-faint">
							{#if agent.provider}
								{agent.provider}/{agent.model}
							{:else}
								<span class="rounded-full border border-edge bg-surface-2 px-1.5 py-0.5 font-mono text-[10px] text-fg-faint">auto</span>
							{/if}
						</td>
						<td class="w-20 px-3 py-2">
							<div class="flex justify-end">
								<CapabilityGlyph features={agent.features} size="md" />
							</div>
						</td>
						{#if onRun}
							<td class="w-10 px-2 py-2">
								<button
									class="flex items-center justify-center rounded-[2px] p-1 text-fg-faint opacity-0 transition-all duration-150 hover:bg-accent-primary/10 hover:text-accent-primary group-hover:opacity-100"
									onclick={(e) => { e.stopPropagation(); onRun(agent); }}
									aria-label="Run {agent.name}"
								>
									<Play size={13} />
								</button>
							</td>
						{/if}
						{#if onDelete}
							<td class="w-10 px-2 py-2">
								<button
									class="flex items-center justify-center rounded-md p-1 text-fg-faint opacity-0 transition-all duration-150 hover:bg-destructive/10 hover:text-destructive group-hover:opacity-100"
									onclick={(e) => { e.stopPropagation(); onDelete(agent); }}
									aria-label="Delete {agent.name}"
								>
									<Trash2 size={13} />
								</button>
							</td>
						{/if}
					</tr>
				{/each}
			</tbody>
		</table>
{/if}
