<script lang="ts">
	import { Handle, Position, type NodeProps } from '@xyflow/svelte';
	import type { McpServer } from '$lib/api/types';

	let { data, selected }: NodeProps<{ server: McpServer }> = $props();

	const srv = $derived(data.server);

	const transportColors: Record<string, string> = {
		stdio: 'border-accent-secondary-muted text-accent-secondary',
		sse: 'border-accent-primary-dim/40 text-accent-primary-dim',
		'streamable-http': 'border-info/30 text-info'
	};

	function healthColor(status: string | null): string {
		if (status === 'healthy') return 'var(--color-ok)';
		if (status === 'degraded') return 'var(--color-warn)';
		if (status === 'unhealthy') return 'var(--color-fail)';
		return 'var(--color-fg-faint)';
	}
</script>

<div
	class="w-[260px] bg-surface-1 p-3 transition-[border-color,box-shadow] duration-200 card-surface
		{selected ? 'active-border' : ''}"
>
	<!-- Name row -->
	<div class="flex items-center gap-2">
		<span
			class="status-dot shrink-0"
			style="background: {healthColor(srv.health_status)}"
		></span>
		<span class="min-w-0 truncate font-mono text-[13px] font-semibold text-fg">
			{srv.display_name}
		</span>
	</div>

	<!-- Transport + tool count -->
	<div class="mt-1.5 flex items-center gap-2">
		<span
			class="rounded-full border px-2 py-0.5 font-mono text-[10px] {transportColors[srv.transport] ?? 'border-edge text-fg-faint'}"
		>
			{srv.transport}
		</span>
		<span class="font-mono text-[11px] text-fg-faint">
			{srv.agent_refs.length} agent{srv.agent_refs.length !== 1 ? 's' : ''}
		</span>
	</div>
</div>

<Handle type="source" position={Position.Right} class="!bg-accent-primary !w-2 !h-2 !border-edge" />
