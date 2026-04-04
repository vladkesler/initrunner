<script lang="ts">
	import type { ProviderStatus } from '$lib/api/builder';
	import { saveProviderKey } from '$lib/api/providers';
	import { ApiError } from '$lib/api/client';
	import { AlertTriangle, Loader2, ExternalLink } from 'lucide-svelte';

	interface Props {
		providerStatus: ProviderStatus[];
		detectedProvider: string | null;
		mode?: 'compact' | 'full';
		onConfigured?: () => void;
	}

	let { providerStatus, detectedProvider, mode = 'compact', onConfigured }: Props = $props();

	const configured = $derived(providerStatus.filter((p) => p.is_configured));
	const unconfigured = $derived(
		providerStatus.filter((p) => !p.is_configured && p.env_var !== '')
	);
	const hasProvider = $derived(configured.length > 0);

	const VALIDATABLE = new Set(['openai', 'anthropic']);

	let selectedProvider = $state('');
	let apiKey = $state('');
	let saving = $state(false);
	let error = $state('');
	let success = $state('');

	const selectedEnvVar = $derived(
		providerStatus.find((p) => p.provider === selectedProvider)?.env_var ?? ''
	);
	const canValidate = $derived(VALIDATABLE.has(selectedProvider));
	const buttonLabel = $derived(
		saving
			? canValidate ? 'Verifying...' : 'Saving...'
			: canValidate ? 'Save & Verify' : 'Save'
	);
	const canSubmit = $derived(
		selectedProvider !== '' &&
		apiKey.trim() !== '' &&
		!saving
	);

	async function handleSave() {
		if (!canSubmit) return;
		saving = true;
		error = '';
		success = '';

		try {
			const result = await saveProviderKey({
				provider: selectedProvider,
				api_key: apiKey.trim(),
				verify: canValidate
			});

			if (result.validation_supported && !result.validated) {
				error = 'Invalid API key';
				return;
			}

			success = result.validation_supported ? 'Verified' : 'Saved';
			apiKey = '';
			selectedProvider = '';

			setTimeout(() => {
				success = '';
				onConfigured?.();
			}, 800);
		} catch (e) {
			error = e instanceof ApiError ? e.detail : String(e);
		} finally {
			saving = false;
		}
	}

	const inputClass = 'w-full border border-edge bg-surface-1 px-3 py-2 font-mono text-[13px] text-fg outline-none transition-[border-color,box-shadow] duration-150 placeholder:text-fg-faint focus:border-accent-primary/40 focus:shadow-[0_0_0_3px_oklch(0.91_0.20_128/0.08)]';
	const inputClassCompact = 'min-w-0 flex-1 border border-edge bg-surface-1 px-2 py-1.5 font-mono text-[13px] text-fg outline-none transition-[border-color,box-shadow] duration-150 placeholder:text-fg-faint focus:border-accent-primary/40 focus:shadow-[0_0_0_3px_oklch(0.91_0.20_128/0.08)]';
</script>

{#if mode === 'full'}
	<div class="space-y-3">
		{#if configured.length > 0}
			<div class="space-y-1">
				{#each configured as prov, i}
					<div
						class="card-surface flex items-center gap-3 bg-surface-1 px-4 py-2.5 transition-[background-color] duration-150 hover:bg-accent-primary/[0.03] animate-fade-in-up"
						style="animation-delay: {i * 60}ms"
					>
						<span class="inline-block h-1.5 w-1.5 shrink-0 rounded-full bg-ok" style="box-shadow: 0 0 4px var(--color-ok)"></span>
						<span class="font-mono text-[13px] text-fg-muted">{prov.provider}</span>
						<span class="ml-auto font-mono text-[12px] text-fg-faint">{prov.env_var}</span>
					</div>
				{/each}
			</div>
		{/if}

		{#if !hasProvider}
			<p class="text-[13px] text-fg-faint">Add an API key to get started.</p>
		{/if}

		<form class="flex flex-wrap items-end gap-3" onsubmit={(e) => { e.preventDefault(); handleSave(); }}>
			<div>
				<label for="prov-select-full" class="mb-1 block section-label">Provider</label>
				<select id="prov-select-full" bind:value={selectedProvider} disabled={saving} class={inputClass}>
					<option value="">Select provider</option>
					{#each unconfigured as prov}
						<option value={prov.provider}>{prov.provider}</option>
					{/each}
									</select>
			</div>
			<div class="flex-1">
				<label for="key-input-full" class="mb-1 block section-label">{selectedEnvVar || 'API Key'}</label>
				<input id="key-input-full" type="password" bind:value={apiKey} disabled={saving} placeholder={selectedEnvVar || 'API key'} class={inputClass} />
			</div>
			<button
				type="submit"
				disabled={!canSubmit}
				class="flex items-center gap-1.5 rounded-[2px] bg-accent-primary px-5 py-2 text-[13px] font-medium text-surface-0 transition-[background-color,box-shadow] duration-150 hover:bg-accent-primary-hover disabled:opacity-40 disabled:hover:shadow-none"
			>
				{#if saving}<Loader2 size={14} class="animate-spin" />{/if}
				{buttonLabel}
			</button>
		</form>
		{#if error}<p class="text-[13px] text-fail">{error}</p>{/if}
		{#if success}<p class="text-[13px] text-ok">{success}</p>{/if}
	</div>

{:else if !hasProvider}
	<div class="border border-warn/30 bg-warn/5 px-4 py-3">
		<form class="flex flex-wrap items-center gap-2" onsubmit={(e) => { e.preventDefault(); handleSave(); }}>
			<AlertTriangle size={14} class="shrink-0 text-warn" />
			<select bind:value={selectedProvider} disabled={saving} class="border border-edge bg-surface-1 px-2 py-1.5 font-mono text-[13px] text-fg outline-none transition-[border-color,box-shadow] duration-150 focus:border-accent-primary/40 focus:shadow-[0_0_0_3px_oklch(0.91_0.20_128/0.08)]">
				<option value="">Provider</option>
				{#each unconfigured as prov}
					<option value={prov.provider}>{prov.provider}</option>
				{/each}
							</select>
			<input type="password" bind:value={apiKey} disabled={saving} placeholder={selectedEnvVar || 'API key'} class={inputClassCompact} />
			<button
				type="submit"
				disabled={!canSubmit}
				class="flex items-center gap-1.5 rounded-[2px] bg-accent-primary px-4 py-1.5 text-[13px] font-medium text-surface-0 transition-[background-color,box-shadow] duration-150 hover:bg-accent-primary-hover disabled:opacity-40 disabled:hover:shadow-none"
			>
				{#if saving}<Loader2 size={12} class="animate-spin" />{/if}
				{buttonLabel}
			</button>
			{#if error}<span class="text-[13px] text-fail">{error}</span>{/if}
			{#if success}<span class="text-[13px] text-ok">{success}</span>{/if}
		</form>
		<div class="mt-2 flex gap-3 pl-[22px]">
			<a href="https://www.initrunner.ai/docs/providers" target="_blank" rel="noopener" class="inline-flex items-center gap-1 text-[13px] text-accent-primary transition-[color] duration-150 hover:text-accent-primary-hover">
				Provider setup guide <ExternalLink size={11} />
			</a>
			<a href="/system" class="text-[13px] text-accent-primary transition-[color] duration-150 hover:text-accent-primary-hover">Manage providers</a>
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
				<span class="inline-block h-1.5 w-1.5 rounded-full bg-ok" style="box-shadow: 0 0 4px var(--color-ok)"></span>
				{prov.provider}
			</span>
		{/each}
	</div>
{/if}
