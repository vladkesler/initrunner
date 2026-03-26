<script lang="ts">
	import type { SaveResult } from '$lib/api/builder';
	import { CheckCircle, Copy, Check } from 'lucide-svelte';

	let {
		saveResult,
		onCreateAnother
	}: {
		saveResult: SaveResult;
		onCreateAnother: () => void;
	} = $props();

	let copied = $state(false);

	async function copyCommand(text: string) {
		await navigator.clipboard.writeText(text);
		copied = true;
		setTimeout(() => (copied = false), 2000);
	}
</script>

<div class="py-8">
	<div class="flex items-center gap-3">
		<CheckCircle size={20} class="text-ok" />
		<h2 class="text-xl font-semibold tracking-[-0.02em] text-fg">Agent created</h2>
	</div>
	<p class="mt-2 font-mono text-[13px] text-fg-muted">{saveResult.path}</p>

	{#if saveResult.issues.length > 0}
		<div class="mt-4 space-y-1">
			{#each saveResult.issues as issue}
				<p class="font-mono text-[13px] text-warn">{issue}</p>
			{/each}
		</div>
	{/if}

	{#if saveResult.next_steps.length > 0}
		<div class="mt-6">
			<h3 class="mb-3 font-mono text-[12px] font-medium uppercase tracking-[0.1em] text-fg-faint">
				Next steps
			</h3>
			<div class="space-y-2">
				{#each saveResult.next_steps as cmd}
					<div class="flex items-center justify-between border border-edge bg-surface-1 px-3 py-2">
						<code class="font-mono text-[13px] text-fg-muted">{cmd}</code>
						<button
							class="ml-3 shrink-0 text-fg-faint transition-[color] duration-150 hover:text-fg-muted"
							onclick={() => copyCommand(cmd)}
							aria-label="Copy command"
						>
							{#if copied}
								<Check size={14} class="text-ok" />
							{:else}
								<Copy size={14} />
							{/if}
						</button>
					</div>
				{/each}
			</div>
		</div>
	{/if}

	<div class="mt-8 flex gap-3">
		<a
			href="/agents/{saveResult.agent_id}"
			class="flex items-center gap-2 rounded-full bg-accent-primary px-6 py-2.5 text-[13px] font-medium text-surface-0 transition-[background-color,box-shadow] duration-150 hover:bg-accent-primary-hover hover:shadow-[0_0_16px_oklch(0.91_0.20_128/0.25)]"
		>
			View Agent
		</a>
		<button
			class="rounded-full border border-edge bg-surface-1 px-5 py-2 text-[13px] font-medium text-fg-muted transition-[color,background-color,border-color] duration-150 hover:bg-surface-2 hover:text-fg hover:border-accent-primary/20"
			onclick={onCreateAnother}
		>
			Create Another
		</button>
	</div>
</div>
