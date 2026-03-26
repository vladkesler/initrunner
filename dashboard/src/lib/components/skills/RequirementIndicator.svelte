<script lang="ts">
	import type { RequirementStatus } from '$lib/api/types';
	import { Tooltip, TooltipContent, TooltipTrigger } from '$lib/components/ui/tooltip';

	let { requirements }: { requirements: RequirementStatus[] } = $props();

	const met = $derived(requirements.filter((r) => r.met).length);
	const total = $derived(requirements.length);
	const allMet = $derived(met === total);
</script>

{#if total > 0}
	<Tooltip>
		<TooltipTrigger class="inline-flex items-center gap-1.5">
			<span
				class="inline-block h-2 w-2 rounded-full {allMet ? 'bg-ok' : 'bg-warn'}"
				style="box-shadow: 0 0 4px var({allMet ? '--color-ok' : '--color-warn'})"
			></span>
			<span class="font-mono text-[12px] text-fg-faint">{met}/{total} met</span>
		</TooltipTrigger>
		<TooltipContent side="bottom" class="max-w-xs border border-edge bg-surface-1 p-2">
			<div class="space-y-1">
				{#each requirements as req}
					<div class="font-mono text-[12px]">
						<span class={req.met ? 'text-ok' : 'text-fail'}>
							{req.met ? '\u2713' : '\u2717'}
						</span>
						<span class="ml-1 text-fg-muted">{req.kind}:{req.name}</span>
						{#if !req.met && req.detail}
							<span class="ml-1 text-fg-faint">({req.detail})</span>
						{/if}
					</div>
				{/each}
			</div>
		</TooltipContent>
	</Tooltip>
{/if}
