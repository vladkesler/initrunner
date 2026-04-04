<script lang="ts">
	import { Handle, Position, type NodeProps } from '@xyflow/svelte';
	import type { McpAgentRef } from '$lib/api/types';
	import { ExternalLink } from 'lucide-svelte';

	let { data, selected }: NodeProps<{ agent: McpAgentRef }> = $props();

	const agt = $derived(data.agent);
</script>

<Handle type="target" position={Position.Left} class="!bg-fg-faint !w-2 !h-2 !border-edge" />

<div
	class="w-[200px] bg-surface-1 p-3 transition-[border-color,box-shadow] duration-200 card-surface
		{selected ? 'active-border' : ''}"
>
	<div class="flex items-center gap-2">
		<span class="min-w-0 truncate font-mono text-[13px] font-semibold text-fg">
			{agt.agent_name}
		</span>
		<span class="ml-auto text-accent-primary">
			<ExternalLink size={11} />
		</span>
	</div>
</div>
