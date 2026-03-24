<script lang="ts">
	import { CheckCircle } from 'lucide-svelte';
	import type { ProviderModels, ProviderPreset } from '$lib/api/types';

	let {
		providers = [],
		customPresets = [],
		ollamaModels: ollamaModelsProp = [],
		ollamaBaseUrl = 'http://localhost:11434/v1',
		selectedProvider = $bindable(''),
		selectedModel = $bindable(''),
		customModelName = $bindable(''),
		customBaseUrl = $bindable(''),
		apiKey = $bindable(''),
		compact = false
	}: {
		providers: ProviderModels[];
		customPresets: ProviderPreset[];
		ollamaModels: string[];
		ollamaBaseUrl: string;
		selectedProvider: string;
		selectedModel: string;
		customModelName: string;
		customBaseUrl: string;
		apiKey: string;
		compact?: boolean;
	} = $props();

	// -- Derived ------------------------------------------------------------------

	const customPresetNames = $derived(new Set(customPresets.map((p) => p.name)));

	const isCustomEndpoint = $derived(customPresetNames.has(selectedProvider));
	const isOllama = $derived(selectedProvider === 'ollama');

	const activePreset = $derived(
		customPresets.find((p) => p.name === selectedProvider) ?? null
	);

	const showEndpointUrl = $derived(
		isOllama || (isCustomEndpoint && selectedProvider === 'custom')
	);

	const cloudProviders = $derived(providers.filter((p) => p.provider !== 'ollama'));

	const ollamaProvider = $derived(providers.find((p) => p.provider === 'ollama'));

	const resolvedOllamaModels = $derived(() => {
		if (ollamaModelsProp.length > 0) return ollamaModelsProp;
		return ollamaProvider?.models.map((m) => m.name) ?? [];
	});

	const filteredModels = $derived(() => {
		if (!selectedProvider) return [] as { name: string; description: string }[];
		if (isOllama) return [];
		const provider = providers.find((p) => p.provider === selectedProvider);
		return provider?.models ?? [];
	});

	// -- Actions ------------------------------------------------------------------

	function selectProvider(provider: string) {
		selectedProvider = provider;
		apiKey = '';
		customModelName = '';

		if (provider === 'ollama') {
			customBaseUrl = '';
			const models = resolvedOllamaModels();
			selectedModel = models[0] ?? '';
		} else if (customPresetNames.has(provider)) {
			customBaseUrl = '';
		} else {
			customBaseUrl = '';
			const p = providers.find((p) => p.provider === provider);
			selectedModel = p?.models[0]?.name ?? '';
		}
	}

	// -- Sizing -------------------------------------------------------------------

	const inputClass = $derived(
		compact
			? 'border border-edge bg-surface-1 px-2 py-1 font-mono text-[12px] text-fg outline-none transition-[border-color] duration-150 focus:border-accent-primary/40'
			: 'border border-edge bg-surface-1 px-3 py-2 font-mono text-[13px] text-fg outline-none transition-[border-color,box-shadow] duration-150 placeholder:text-fg-faint focus:border-accent-primary/40 focus:shadow-[0_0_0_3px_oklch(0.91_0.20_128/0.08)]'
	);

	const selectClass = $derived(
		compact
			? 'border border-edge bg-surface-1 px-2 py-1 font-mono text-[12px] text-fg outline-none'
			: 'border border-edge bg-surface-1 px-3 py-2 font-mono text-[13px] text-fg outline-none'
	);

	const labelClass = $derived(
		compact
			? 'font-mono text-[11px] text-fg-faint'
			: 'mb-3 font-mono text-[12px] font-medium uppercase tracking-[0.1em] text-fg-faint'
	);
</script>

<div class="space-y-3">
	<!-- Provider / Model row -->
	<div class={compact ? 'space-y-2' : ''}>
		{#if !compact}
			<h2 class={labelClass}>Model</h2>
		{/if}
		<div class="flex gap-{compact ? '2' : '3'}">
			<select
				class={selectClass}
				value={selectedProvider}
				onchange={(e) => selectProvider(e.currentTarget.value)}
			>
				<optgroup label="Cloud">
					{#each cloudProviders as p}
						<option value={p.provider}>{p.provider}</option>
					{/each}
				</optgroup>
				{#if ollamaProvider}
					<optgroup label="Local">
						<option value="ollama">ollama</option>
					</optgroup>
				{/if}
				{#if customPresets.length > 0}
					<optgroup label="Custom endpoint">
						{#each customPresets as preset}
							<option value={preset.name}>{preset.label}</option>
						{/each}
					</optgroup>
				{/if}
			</select>

			{#if isCustomEndpoint}
				<input
					type="text"
					bind:value={customModelName}
					placeholder={activePreset?.placeholder ?? 'model-name'}
					class="min-w-0 flex-1 {inputClass}"
				/>
			{:else if isOllama}
				<select
					class="min-w-0 flex-1 {selectClass}"
					bind:value={selectedModel}
				>
					{#each resolvedOllamaModels() as m}
						<option value={m}>{m}</option>
					{/each}
				</select>
			{:else}
				<select
					class="min-w-0 flex-1 {selectClass}"
					bind:value={selectedModel}
				>
					{#each filteredModels() as m}
						<option value={m.name}>{compact ? m.name : `${m.name} -- ${m.description}`}</option>
					{/each}
				</select>
			{/if}
		</div>
	</div>

	<!-- Endpoint URL -->
	{#if showEndpointUrl}
		<div>
			{#if !compact}
				<h2 class={labelClass}>Endpoint</h2>
			{:else}
				<span class={labelClass}>endpoint</span>
			{/if}
			<input
				type="text"
				bind:value={customBaseUrl}
				placeholder={isOllama ? ollamaBaseUrl : 'https://...'}
				class="w-full {inputClass}"
			/>
		</div>
	{/if}

	<!-- API Key -->
	{#if isCustomEndpoint}
		<div>
			{#if !compact}
				<h2 class={labelClass}>API Key</h2>
			{:else}
				<span class={labelClass}>api key</span>
			{/if}
			{#if activePreset?.key_configured && !apiKey}
				<p class="flex items-center gap-1.5 text-[{compact ? '11' : '13'}px] text-status-ok">
					<CheckCircle size={compact ? 11 : 13} />
					Already configured
				</p>
			{:else}
				<input
					type="password"
					bind:value={apiKey}
					placeholder="Paste your API key"
					class="w-full {inputClass}"
				/>
				{#if activePreset?.key_configured}
					<p class="mt-1 text-[{compact ? '10' : '13'}px] text-fg-faint">
						Leave empty to use the existing key
					</p>
				{/if}
			{/if}
		</div>
	{/if}
</div>
