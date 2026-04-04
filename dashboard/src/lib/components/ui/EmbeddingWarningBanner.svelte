<script lang="ts">
	import type { EmbeddingWarning } from '$lib/api/builder';
	import { setEmbeddingProvider } from '$lib/api/builder';
	import { saveProviderKey } from '$lib/api/providers';
	import { ApiError } from '$lib/api/client';
	import { AlertTriangle, Loader2 } from 'lucide-svelte';

	const VALIDATABLE = new Set(['openai']);

	let {
		warning,
		yamlText,
		onResolved
	}: {
		warning: EmbeddingWarning;
		yamlText: string;
		onResolved: (result: { yaml_text: string; embedding_warning: EmbeddingWarning | null }) => void;
	} = $props();

	let userPickedProvider: string | null = $state(null);
	let apiKey = $state('');
	let saving = $state(false);
	let applying = $state(false);
	let error = $state('');
	let success = $state('');

	const selectedProvider = $derived(userPickedProvider ?? warning.current_provider);

	const selectedOption = $derived(
		warning.options.find((o) => o.provider === selectedProvider)
	);
	const isOllama = $derived(selectedProvider === 'ollama');
	const isConfigured = $derived(selectedOption?.is_configured ?? false);
	const canValidate = $derived(VALIDATABLE.has(selectedProvider));
	const saveLabel = $derived(
		saving
			? canValidate ? 'Verifying...' : 'Saving...'
			: canValidate ? 'Save & Verify' : 'Save'
	);

	async function handleSaveKey() {
		if (!apiKey.trim() || saving) return;
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

			// Re-validate to clear warning. If user picked a non-default provider,
			// also patch the YAML.
			setTimeout(async () => {
				if (selectedProvider !== warning.current_provider) {
					await handleApply();
				} else {
					// Trigger re-validation via the validate endpoint
					const { validateYaml } = await import('$lib/api/builder');
					const res = await validateYaml(yamlText);
					onResolved({
						yaml_text: res.yaml_text,
						embedding_warning: res.embedding_warning
					});
				}
				success = '';
			}, 600);
		} catch (e) {
			error = e instanceof ApiError ? e.detail : String(e);
		} finally {
			saving = false;
		}
	}

	async function handleApply() {
		if (applying) return;
		applying = true;
		error = '';

		try {
			const result = await setEmbeddingProvider({
				yaml_text: yamlText,
				embedding_provider: selectedProvider
			});
			onResolved({
				yaml_text: result.yaml_text,
				embedding_warning: result.embedding_warning
			});
		} catch (e) {
			error = e instanceof ApiError ? e.detail : String(e);
		} finally {
			applying = false;
		}
	}
</script>

<div class="border-l-2 border-l-warn bg-warn/5 px-4 py-3 space-y-3">
	<!-- Message -->
	<div class="flex items-start gap-2.5">
		<AlertTriangle size={14} class="mt-0.5 shrink-0 text-warn" />
		<p class="text-[13px] text-fg-muted">{warning.message}</p>
	</div>

	<!-- Provider chips -->
	<div class="flex flex-wrap items-center gap-2 pl-[22px]">
		<span class="section-label">
			Embeddings
		</span>
		{#each warning.options as option}
			<button
				class="inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 font-mono text-[12px] transition-[color,background-color,border-color] duration-150
					{selectedProvider === option.provider
						? 'border-accent-primary/30 bg-accent-primary/10 text-accent-primary'
						: option.is_configured
							? 'border-ok/30 bg-ok/10 text-ok hover:bg-ok/15'
							: 'border-edge bg-surface-1 text-fg-faint hover:bg-surface-2'}"
				onclick={() => { userPickedProvider = option.provider; error = ''; success = ''; apiKey = ''; }}
			>
				{#if option.is_configured}
					<span class="inline-block h-1.5 w-1.5 rounded-full bg-ok" style="box-shadow: 0 0 4px var(--color-ok)"></span>
				{/if}
				{option.provider}
			</button>
		{/each}
	</div>

	<!-- Action area -->
	<div class="pl-[22px]">
		{#if isOllama && !isConfigured}
			<p class="text-[13px] text-fg-faint">
				Start Ollama to use local embeddings.
				<a href="/system" class="text-accent-primary transition-[color] duration-150 hover:text-accent-primary-hover">
					System status
				</a>
			</p>
		{:else if isConfigured && selectedProvider !== warning.current_provider}
			<!-- Configured alternative -- offer to switch -->
			<div class="flex items-center gap-2">
				<span class="text-[13px] text-ok">Ready</span>
				<button
					class="flex items-center gap-1.5 rounded-[2px] bg-accent-primary px-4 py-1.5 text-[13px] font-medium text-surface-0 transition-[background-color,box-shadow] duration-150 hover:bg-accent-primary-hover disabled:opacity-40"
					disabled={applying}
					onclick={handleApply}
				>
					{#if applying}<Loader2 size={12} class="animate-spin" />{/if}
					Use {selectedProvider} embeddings
				</button>
			</div>
		{:else if isConfigured}
			<span class="text-[13px] text-ok">Configured</span>
		{:else}
			<!-- Unconfigured cloud provider -- inline key form -->
			<form class="flex items-center gap-2" onsubmit={(e) => { e.preventDefault(); handleSaveKey(); }}>
				<input
					type="password"
					bind:value={apiKey}
					disabled={saving}
					placeholder={selectedOption?.env_var || 'API key'}
					class="min-w-0 flex-1 border border-edge bg-surface-1 px-2 py-1.5 font-mono text-[13px] text-fg outline-none transition-[border-color,box-shadow] duration-150 placeholder:text-fg-faint focus:border-accent-primary/40 focus:shadow-[0_0_0_3px_oklch(0.91_0.20_128/0.08)]"
				/>
				<button
					type="submit"
					disabled={!apiKey.trim() || saving}
					class="flex items-center gap-1.5 rounded-[2px] bg-accent-primary px-4 py-1.5 text-[13px] font-medium text-surface-0 transition-[background-color,box-shadow] duration-150 hover:bg-accent-primary-hover disabled:opacity-40"
				>
					{#if saving}<Loader2 size={12} class="animate-spin" />{/if}
					{saveLabel}
				</button>
			</form>
		{/if}

		{#if error}<p class="mt-1.5 text-[13px] text-fail">{error}</p>{/if}
		{#if success}<p class="mt-1.5 text-[13px] text-ok">{success}</p>{/if}
	</div>
</div>
