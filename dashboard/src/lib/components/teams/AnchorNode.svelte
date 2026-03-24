<script lang="ts">
	import { Handle, Position, type NodeProps } from '@xyflow/svelte';

	let { data }: NodeProps<{ label: string; hasTarget: boolean; hasSource: boolean }> = $props();
</script>

{#if data.hasTarget}
	<Handle type="target" position={Position.Top} class="!bg-accent-primary !w-2 !h-2 !border-edge" />
{/if}

<div class="w-[200px] border border-accent-primary/30 bg-accent-primary/5 px-4 py-2 text-center font-mono text-[12px] text-accent-primary">
	{data.label}
</div>

{#if data.hasSource}
	<Handle type="source" position={Position.Bottom} class="!bg-accent-primary !w-2 !h-2 !border-edge" />
{/if}
