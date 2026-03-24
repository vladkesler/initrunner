<script lang="ts">
	import { ChevronUp, ChevronDown, X } from 'lucide-svelte';
	import ModelSelector from '$lib/components/ui/ModelSelector.svelte';
	import type { ProviderModels, ProviderPreset } from '$lib/api/types';

	let {
		index,
		name,
		role,
		modelOverride,
		modelProvider,
		modelName,
		modelCustomName,
		modelBaseUrl,
		modelApiKey,
		strategy,
		canRemove,
		canMoveUp,
		canMoveDown,
		providers,
		customPresets,
		ollamaModels,
		ollamaBaseUrl,
		nameError,
		onUpdate,
		onRemove,
		onMoveUp,
		onMoveDown
	}: {
		index: number;
		name: string;
		role: string;
		modelOverride: boolean;
		modelProvider: string;
		modelName: string;
		modelCustomName: string;
		modelBaseUrl: string;
		modelApiKey: string;
		strategy: 'sequential' | 'parallel';
		canRemove: boolean;
		canMoveUp: boolean;
		canMoveDown: boolean;
		providers: ProviderModels[];
		customPresets: ProviderPreset[];
		ollamaModels: string[];
		ollamaBaseUrl: string;
		nameError: string | null;
		onUpdate: (field: string, value: any) => void;
		onRemove: () => void;
		onMoveUp: () => void;
		onMoveDown: () => void;
	} = $props();

	const NAME_RE = /^[a-z0-9][a-z0-9-]*[a-z0-9]$/;

	function sanitizeName(raw: string): string {
		return raw
			.toLowerCase()
			.replace(/[^a-z0-9-]/g, '-')
			.replace(/-{2,}/g, '-')
			.replace(/^-+|-+$/g, '');
	}

	function handleNameBlur() {
		const sanitized = sanitizeName(name);
		if (sanitized !== name) {
			onUpdate('name', sanitized);
		}
	}

	function toggleOverride(enabled: boolean) {
		onUpdate('modelOverride', enabled);
		if (enabled && !modelProvider && providers.length > 0) {
			onUpdate('modelProvider', providers[0].provider);
			if (providers[0].models.length > 0) {
				onUpdate('modelName', providers[0].models[0].name);
			}
		}
	}
</script>

<div
	class="border border-edge bg-surface-1 p-4 transition-[border-color] duration-150"
	style="animation: fadeIn 200ms ease-out {index * 40}ms both"
>
	<!-- Header row -->
	<div class="flex items-center gap-2">
		{#if strategy === 'sequential'}
			<span
				class="flex h-5 w-5 shrink-0 items-center justify-center rounded-full border border-accent-primary/20 bg-accent-primary/5 font-mono text-[10px] text-accent-primary"
			>
				{index + 1}
			</span>
		{/if}

		<input
			type="text"
			value={name}
			oninput={(e) => onUpdate('name', e.currentTarget.value)}
			onblur={handleNameBlur}
			placeholder="persona-name"
			class="min-w-0 flex-1 border-b border-transparent bg-transparent font-mono text-[13px] font-medium text-fg outline-none transition-[border-color] duration-150 placeholder:text-fg-faint focus:border-accent-primary/40"
		/>

		<div class="flex shrink-0 items-center gap-0.5">
			{#if strategy === 'sequential'}
				<button
					class="p-0.5 text-fg-faint transition-[color] duration-150 hover:text-fg-muted disabled:opacity-20"
					onclick={onMoveUp}
					disabled={!canMoveUp}
					aria-label="Move up"
				>
					<ChevronUp size={14} />
				</button>
				<button
					class="p-0.5 text-fg-faint transition-[color] duration-150 hover:text-fg-muted disabled:opacity-20"
					onclick={onMoveDown}
					disabled={!canMoveDown}
					aria-label="Move down"
				>
					<ChevronDown size={14} />
				</button>
			{/if}
			<button
				class="p-0.5 text-fg-faint transition-[color] duration-150 hover:text-status-fail disabled:opacity-20"
				onclick={onRemove}
				disabled={!canRemove}
				aria-label="Remove persona"
			>
				<X size={14} />
			</button>
		</div>
	</div>

	<!-- Name validation error -->
	{#if nameError}
		<p class="mt-1 font-mono text-[11px] text-status-fail">{nameError}</p>
	{/if}

	<!-- Role textarea -->
	<textarea
		value={role}
		oninput={(e) => onUpdate('role', e.currentTarget.value)}
		placeholder="Describe this persona's role..."
		rows="2"
		class="mt-3 w-full resize-none border border-edge bg-surface-0 px-2.5 py-2 font-mono text-[12px] text-fg outline-none transition-[border-color] duration-150 placeholder:text-fg-faint focus:border-accent-primary/40"
	></textarea>

	<!-- Model override toggle -->
	<div class="mt-3">
		<label class="flex items-center gap-2 font-mono text-[11px] text-fg-faint">
			<input
				type="checkbox"
				checked={modelOverride}
				onchange={(e) => toggleOverride(e.currentTarget.checked)}
				class="accent-accent-primary"
			/>
			Override model
		</label>

		{#if modelOverride}
			<div class="mt-2 rounded border border-edge/50 bg-surface-0 p-2.5">
				<ModelSelector
					{providers}
					{customPresets}
					{ollamaModels}
					{ollamaBaseUrl}
					compact={true}
					bind:selectedProvider={modelProvider}
					bind:selectedModel={modelName}
					bind:customModelName={modelCustomName}
					bind:customBaseUrl={modelBaseUrl}
					bind:apiKey={modelApiKey}
				/>
			</div>
		{/if}
	</div>
</div>
