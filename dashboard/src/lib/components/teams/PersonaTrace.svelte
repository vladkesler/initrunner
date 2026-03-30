<script lang="ts">
	import type { PersonaStepResponse } from '$lib/api/types';
	import { ChevronRight, CheckCircle, XCircle } from 'lucide-svelte';

	let { steps }: { steps: PersonaStepResponse[] } = $props();

	let expanded = $state(false);

	const totalDuration = $derived(steps.reduce((sum, s) => sum + s.duration_ms, 0));
	const hasRounds = $derived(steps.some((s) => s.round_num != null));

	// Group steps by round for debate display
	type RoundGroup = { label: string; steps: PersonaStepResponse[] };
	const roundGroups = $derived.by((): RoundGroup[] => {
		if (!hasRounds) return [{ label: '', steps }];
		const groups: RoundGroup[] = [];
		const byRound = new Map<string, PersonaStepResponse[]>();
		for (const s of steps) {
			const key =
				s.step_kind === 'synthesis'
					? 'synthesis'
					: s.round_num != null
						? `round-${s.round_num}`
						: 'other';
			if (!byRound.has(key)) byRound.set(key, []);
			byRound.get(key)!.push(s);
		}
		for (const [key, groupSteps] of byRound) {
			const label =
				key === 'synthesis'
					? 'Synthesis'
					: key.startsWith('round-')
						? `Round ${key.split('-')[1]}`
						: '';
			groups.push({ label, steps: groupSteps });
		}
		return groups;
	});

	const maxRounds = $derived(steps.find((s) => s.max_rounds != null)?.max_rounds ?? null);
	const summaryLabel = $derived(
		hasRounds && maxRounds != null
			? `${maxRounds} rounds, ${steps.length} steps, ${totalDuration}ms`
			: `${steps.length} persona${steps.length !== 1 ? 's' : ''}, ${totalDuration}ms`
	);
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
		<span class="font-mono">{summaryLabel}</span>
	</button>

	{#if expanded}
		<div class="mt-2 ml-1 space-y-0">
			{#each roundGroups as group}
				{#if group.label}
					<div class="mb-1 mt-3 first:mt-0">
						<span class="font-mono text-[11px] font-medium tracking-wide text-fg-faint/60">
							{group.label}
						</span>
						<div class="mt-0.5 h-px bg-fg-faint/10"></div>
					</div>
				{/if}
				{#each group.steps as step, idx}
					<div class="flex gap-3">
						<!-- Vertical connector -->
						<div class="flex flex-col items-center">
							<div class="flex h-5 w-5 shrink-0 items-center justify-center">
								{#if step.success}
									<CheckCircle size={12} class="text-ok" />
								{:else}
									<XCircle size={12} class="text-fail" />
								{/if}
							</div>
							{#if idx < group.steps.length - 1}
								<div class="w-px flex-1 bg-fg-faint/20"></div>
							{/if}
						</div>

						<!-- Step content -->
						<div class="pb-3">
							<div class="flex items-center gap-2">
								<span class="font-mono text-[13px] font-semibold text-fg">{step.persona_name}</span>
								<span
									class="font-mono text-[11px] text-fg-faint"
									style="font-variant-numeric: tabular-nums"
								>
									{step.duration_ms}ms
								</span>
								<span
									class="font-mono text-[11px] text-fg-faint"
									style="font-variant-numeric: tabular-nums"
								>
									{step.tokens_in}+{step.tokens_out} tok
								</span>
							</div>
							{#if step.error}
								<p class="mt-0.5 text-[11px] text-fail">{step.error}</p>
							{:else if step.output}
								<p class="mt-0.5 line-clamp-3 text-[11px] text-fg-muted">
									{step.output.length > 300 ? step.output.slice(0, 300) + '...' : step.output}
								</p>
							{/if}
						</div>
					</div>
				{/each}
			{/each}
		</div>
	{/if}
</div>
