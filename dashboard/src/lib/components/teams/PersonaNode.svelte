<script lang="ts">
	import { Handle, Position, type NodeProps } from '@xyflow/svelte';
	import type { PersonaDetail, PersonaStepResponse } from '$lib/api/types';
	import { CheckCircle, XCircle, Wrench } from 'lucide-svelte';

	let { data, selected }: NodeProps<{
		persona: PersonaDetail;
		state: 'idle' | 'active' | 'complete' | 'error' | 'pending';
		step: PersonaStepResponse | null;
	}> = $props();

	const persona = $derived(data.persona);
	const state = $derived(data.state);
	const step = $derived(data.step);
</script>

<Handle type="target" position={Position.Top} class="!bg-fg-faint !w-2 !h-2 !border-edge" />

<div
	class="w-[240px] bg-surface-1 p-3 transition-[border-color,box-shadow] duration-200
		{state === 'error' ? 'card-surface-error' : 'card-surface'}
		{state === 'active' ? 'glow-lime-subtle' : ''}
		{selected ? 'glow-lime' : ''}
		{state === 'pending' ? 'opacity-40' : ''}"
>
	<!-- Name row -->
	<div class="flex items-center justify-between gap-2">
		<div class="flex items-center gap-2">
			{#if state === 'complete'}
				<CheckCircle size={14} class="shrink-0 text-status-ok" />
			{:else if state === 'error'}
				<XCircle size={14} class="shrink-0 text-status-fail" />
			{:else if state === 'active'}
				<span class="inline-block h-2 w-2 animate-pulse rounded-full bg-accent-primary"></span>
			{/if}
			<span class="min-w-0 truncate font-mono text-[13px] font-semibold text-fg">{persona.name}</span>
		</div>
		<div class="flex shrink-0 items-center gap-1.5">
			{#if persona.model}
				<span class="rounded-full border border-accent-secondary/20 bg-accent-secondary/10 px-1.5 py-0.5 font-mono text-[10px] text-accent-secondary">
					{persona.model.name ?? 'override'}
				</span>
			{/if}
			{#if persona.tools.length > 0}
				<span class="flex items-center gap-0.5 rounded-full border border-edge bg-surface-2 px-1.5 py-0.5 font-mono text-[10px] text-fg-faint">
					<Wrench size={9} />
					{persona.tools.length}
				</span>
			{/if}
		</div>
	</div>

	<!-- Role -->
	{#if persona.role}
		<p class="mt-1 line-clamp-2 text-[12px] text-fg-faint">{persona.role}</p>
	{/if}

	<!-- Step metrics -->
	{#if step}
		<div class="mt-1.5 font-mono text-[11px] text-fg-faint" style="font-variant-numeric: tabular-nums">
			{step.duration_ms}ms / {step.tokens_in}+{step.tokens_out} tok
		</div>
	{/if}
</div>

<Handle type="source" position={Position.Bottom} class="!bg-accent-primary !w-2 !h-2 !border-edge" />
