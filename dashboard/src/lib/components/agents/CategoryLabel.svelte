<script lang="ts">
	import type { NodeProps } from '@xyflow/svelte';
	import { Wrench, Zap, BookOpen, Plug, Sparkles, Brain, AlertTriangle, Box, Layers } from 'lucide-svelte';

	let { data }: NodeProps<{ label: string; icon: string; count: number }> = $props();

	const icons: Record<string, any> = {
		Zap, Wrench, BookOpen, Plug, Sparkles, Brain, AlertTriangle, Box, Layers,
	};

	const Icon = $derived(icons[data.icon] ?? Layers);
</script>

<div class="flex select-none items-center gap-2 pointer-events-none">
	<Icon size={14} strokeWidth={1.5} class="text-fg-faint" />
	<span class="font-mono text-[11px] font-medium uppercase tracking-[0.12em] text-fg-faint">
		{data.label}
	</span>
	<span class="font-mono text-[11px] text-fg-faint/50">
		{data.count}
	</span>
</div>
