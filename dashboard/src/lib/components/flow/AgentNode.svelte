<script lang="ts">
	import { Handle, Position, type NodeProps } from '@xyflow/svelte';
	import type { FlowAgentDetail } from '$lib/api/types';
	import {
		Zap,
		HeartPulse,
		ShieldAlert,
		ArrowRight,
		ExternalLink
	} from 'lucide-svelte';

	let { data, selected }: NodeProps<{ agent: FlowAgentDetail }> = $props();

	const agt = $derived(data.agent);

	const hasTrigger = $derived(agt.trigger_summary !== null);
	const hasHealthCheck = $derived(
		agt.health_check.interval_seconds !== 30 ||
		agt.health_check.timeout_seconds !== 10 ||
		agt.health_check.retries !== 3
	);
	const hasCircuitBreaker = $derived(agt.sink?.circuit_breaker_threshold !== null && agt.sink?.circuit_breaker_threshold !== undefined);
	const hasSink = $derived(agt.sink !== null && agt.sink.targets.length > 0);
	const capCount = $derived(
		(hasTrigger ? 1 : 0) + (hasHealthCheck ? 1 : 0) + (hasCircuitBreaker ? 1 : 0) + (hasSink ? 1 : 0)
	);
	const isRich = $derived(capCount >= 3);
</script>

<Handle type="target" position={Position.Left} class="!bg-fg-faint !w-2 !h-2 !border-edge" />

<div
	class="w-[240px] bg-surface-1 p-3 transition-[border-color,box-shadow] duration-200 card-surface
		{isRich ? 'glow-lime-subtle' : ''}
		{selected ? 'glow-lime' : ''}"
>
	<!-- Name row -->
	<div class="flex items-center gap-2">
		<span class="min-w-0 truncate font-mono text-[13px] font-semibold text-fg">{agt.name}</span>
		<div class="ml-auto flex items-center gap-1.5">
			{#if hasTrigger}
				<Zap size={11} strokeWidth={1.5} class="text-accent-secondary" />
			{/if}
			{#if hasHealthCheck}
				<HeartPulse size={11} strokeWidth={1.5} class="text-status-ok" />
			{/if}
			{#if hasCircuitBreaker}
				<ShieldAlert size={11} strokeWidth={1.5} class="text-status-warn" />
			{/if}
			{#if hasSink}
				<ArrowRight size={11} strokeWidth={1.5} class="text-fg-faint" />
			{/if}
		</div>
	</div>

	<!-- Agent / role link -->
	<div class="mt-1 text-[12px] text-fg-faint">
		{#if agt.agent_id}
			<span class="inline-flex items-center gap-1 text-accent-primary">
				{agt.agent_name || agt.role_path}
				<ExternalLink size={10} />
			</span>
		{:else}
			<span class="font-mono">{agt.role_path}</span>
		{/if}
	</div>

	<!-- Sink summary -->
	{#if agt.sink}
		<div class="mt-1 font-mono text-[11px] text-fg-faint/70">{agt.sink.summary}</div>
	{/if}

	<!-- Restart badge -->
	{#if agt.restart.condition !== 'none'}
		<div class="mt-1.5 inline-block border border-edge bg-surface-2 px-1.5 py-0.5 font-mono text-[10px] text-fg-faint">
			{agt.restart.condition}
		</div>
	{/if}
</div>

{#if hasSink}
	<Handle type="source" position={Position.Right} class="!bg-accent-primary !w-2 !h-2 !border-edge" />
{/if}
