<script lang="ts">
	import { Handle, Position, type NodeProps } from '@xyflow/svelte';
	import type { ComposeServiceDetail } from '$lib/api/types';
	import {
		Zap,
		HeartPulse,
		ShieldAlert,
		ArrowRight,
		ExternalLink
	} from 'lucide-svelte';

	let { data, selected }: NodeProps<{ service: ComposeServiceDetail }> = $props();

	const svc = $derived(data.service);

	const hasTrigger = $derived(svc.trigger_summary !== null);
	const hasHealthCheck = $derived(
		svc.health_check.interval_seconds !== 30 ||
		svc.health_check.timeout_seconds !== 10 ||
		svc.health_check.retries !== 3
	);
	const hasCircuitBreaker = $derived(svc.sink?.circuit_breaker_threshold !== null && svc.sink?.circuit_breaker_threshold !== undefined);
	const hasSink = $derived(svc.sink !== null && svc.sink.targets.length > 0);
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
		<span class="min-w-0 truncate font-mono text-[13px] font-semibold text-fg">{svc.name}</span>
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
		{#if svc.agent_id}
			<span class="inline-flex items-center gap-1 text-accent-primary">
				{svc.agent_name || svc.role_path}
				<ExternalLink size={10} />
			</span>
		{:else}
			<span class="font-mono">{svc.role_path}</span>
		{/if}
	</div>

	<!-- Sink summary -->
	{#if svc.sink}
		<div class="mt-1 font-mono text-[11px] text-fg-faint/70">{svc.sink.summary}</div>
	{/if}

	<!-- Restart badge -->
	{#if svc.restart.condition !== 'none'}
		<div class="mt-1.5 inline-block border border-edge bg-surface-2 px-1.5 py-0.5 font-mono text-[10px] text-fg-faint">
			{svc.restart.condition}
		</div>
	{/if}
</div>

{#if hasSink}
	<Handle type="source" position={Position.Right} class="!bg-accent-primary !w-2 !h-2 !border-edge" />
{/if}
