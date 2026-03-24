<script lang="ts">
	import type { ServiceStepResponse } from '$lib/api/types';
	import { ChevronRight, CheckCircle, XCircle } from 'lucide-svelte';

	let { steps }: { steps: ServiceStepResponse[] } = $props();

	let expanded = $state(false);

	const totalDuration = $derived(steps.reduce((sum, s) => sum + s.duration_ms, 0));
</script>

<div class="mt-2">
	<button
		class="flex items-center gap-1.5 text-[12px] text-fg-faint transition-[color] duration-150 hover:text-fg-muted"
		onclick={() => (expanded = !expanded)}
		aria-expanded={expanded}
	>
		<ChevronRight
			size={12}
			class="shrink-0 transition-transform duration-150 {expanded ? 'rotate-90' : ''}"
		/>
		<span class="font-mono">{steps.length} service{steps.length !== 1 ? 's' : ''}, {totalDuration}ms</span>
	</button>

	{#if expanded}
		<div class="mt-2 ml-1 space-y-0">
			{#each steps as step, idx}
				<div class="flex gap-3">
					<!-- Vertical connector -->
					<div class="flex flex-col items-center">
						<div class="flex h-5 w-5 shrink-0 items-center justify-center">
							{#if step.success}
								<CheckCircle size={12} class="text-status-ok" />
							{:else}
								<XCircle size={12} class="text-status-fail" />
							{/if}
						</div>
						{#if idx < steps.length - 1}
							<div class="w-px flex-1 bg-fg-faint/20"></div>
						{/if}
					</div>

					<!-- Step content -->
					<div class="pb-3">
						<div class="flex items-center gap-2">
							<span class="font-mono text-[13px] font-semibold text-fg">{step.service_name}</span>
							<span class="font-mono text-[11px] text-fg-faint" style="font-variant-numeric: tabular-nums">
								{step.duration_ms}ms
							</span>
							<span class="font-mono text-[11px] text-fg-faint" style="font-variant-numeric: tabular-nums">
								{step.tokens_in}+{step.tokens_out} tok
							</span>
						</div>
						{#if step.error}
							<p class="mt-0.5 text-[11px] text-status-fail">{step.error}</p>
						{:else if step.output}
							<p class="mt-0.5 line-clamp-2 text-[11px] text-fg-muted">{step.output}</p>
						{/if}
					</div>
				</div>
			{/each}
		</div>
	{/if}
</div>
