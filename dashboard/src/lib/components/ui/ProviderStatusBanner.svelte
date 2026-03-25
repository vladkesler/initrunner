<script lang="ts">
	import type { ProviderStatus } from '$lib/api/builder';
	import { AlertTriangle } from 'lucide-svelte';

	interface Props {
		providerStatus: ProviderStatus[];
		detectedProvider: string | null;
	}

	let { providerStatus, detectedProvider }: Props = $props();

	const configured = $derived(providerStatus.filter((p) => p.is_configured));
	const hasProvider = $derived(configured.length > 0);
</script>

{#if !hasProvider}
	<div class="border border-warn/30 bg-warn/5 px-4 py-3">
		<div class="flex items-start gap-2">
			<AlertTriangle size={14} class="mt-0.5 shrink-0 text-warn" />
			<div>
				<p class="text-[13px] text-fg-muted">
					No AI provider configured. Set an API key or start Ollama to run agents.
				</p>
				<div class="mt-2 flex gap-3">
					<a
						href="https://www.initrunner.ai/docs/providers"
						target="_blank"
						rel="noopener"
						class="text-[13px] text-accent-primary transition-[color] duration-150 hover:text-accent-primary-hover"
					>
						Provider setup guide
					</a>
					<a
						href="https://www.initrunner.ai/docs/quickstart"
						target="_blank"
						rel="noopener"
						class="text-[13px] text-accent-primary transition-[color] duration-150 hover:text-accent-primary-hover"
					>
						Quickstart guide
					</a>
				</div>
			</div>
		</div>
	</div>
{:else}
	<div class="flex flex-wrap gap-2">
		{#each configured as prov}
			<span
				class="inline-flex items-center gap-1.5 rounded-full px-3 py-1 font-mono text-[12px]
					{prov.provider === detectedProvider
					? 'border border-accent-primary/30 bg-accent-primary/10 text-accent-primary'
					: 'border border-edge bg-surface-1 text-fg-faint'}"
			>
				<span
					class="inline-block h-1.5 w-1.5 rounded-full bg-ok"
					style="box-shadow: 0 0 4px var(--color-ok)"
				></span>
				{prov.provider}
			</span>
		{/each}
	</div>
{/if}
