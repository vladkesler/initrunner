<script lang="ts">
	import type { BuilderOptions, HubSearchResult } from '$lib/api/builder';
	import { Skeleton } from '$lib/components/ui/skeleton';
	import ProviderStatusBanner from '$lib/components/ui/ProviderStatusBanner.svelte';
	import ModelSelector from '$lib/components/ui/ModelSelector.svelte';
	import HubSearchPanel from './HubSearchPanel.svelte';
	import {
		LayoutTemplate,
		Sparkles,
		FileCode,
		Globe,
		Import,
		Loader2,
		ExternalLink,
		Copy,
		Check
	} from 'lucide-svelte';

	type Mode = 'description' | 'template' | 'blank' | 'hub' | 'langchain';

	let {
		options,
		mode = $bindable(null),
		agentName = $bindable(''),
		description = $bindable(''),
		langchainSource = $bindable(''),
		selectedTemplate = $bindable(null),
		selectedProvider = $bindable(''),
		selectedModel = $bindable(''),
		customModelName = $bindable(''),
		customBaseUrl = $bindable(''),
		apiKey = $bindable(''),
		hubQuery = $bindable(''),
		hubResults,
		hubSearching,
		hubError,
		selectedHubRef = $bindable(null),
		hubFeaturedResults,
		hubFeaturedLoading,
		onHubQueryInput,
		onHubSelectResult,
		generating,
		generateError,
		canGenerate,
		generateButtonLabel,
		noProviders,
		onGenerate,
		onReloadOptions,
		onSelectMode
	}: {
		options: BuilderOptions;
		mode: Mode | null;
		agentName: string;
		description: string;
		langchainSource: string;
		selectedTemplate: string | null;
		selectedProvider: string;
		selectedModel: string;
		customModelName: string;
		customBaseUrl: string;
		apiKey: string;
		hubQuery: string;
		hubResults: HubSearchResult[];
		hubSearching: boolean;
		hubError: string | null;
		selectedHubRef: string | null;
		hubFeaturedResults: HubSearchResult[];
		hubFeaturedLoading: boolean;
		onHubQueryInput: () => void;
		onHubSelectResult: (result: HubSearchResult) => void;
		generating: boolean;
		generateError: string | null;
		canGenerate: () => boolean;
		generateButtonLabel: string;
		noProviders: boolean;
		onGenerate: () => void;
		onReloadOptions: () => void;
		onSelectMode: (m: Mode) => void;
	} = $props();

	let setupCopied = $state(false);

	const templateSetup = $derived(
		(selectedTemplate && options?.template_setups?.[selectedTemplate]) || null
	);

	const modeCards: { id: Mode; label: string; desc: string; icon: typeof LayoutTemplate }[] = [
		{ id: 'description', label: 'Describe', desc: 'AI generates YAML', icon: Sparkles },
		{ id: 'template', label: 'Template', desc: 'Start from a preset', icon: LayoutTemplate },
		{ id: 'blank', label: 'Blank', desc: 'Minimal skeleton', icon: FileCode },
		{ id: 'hub', label: 'InitHub', desc: 'Browse hub.initrunner.ai', icon: Globe },
		{ id: 'langchain', label: 'Import', desc: 'From LangChain code', icon: Import }
	];

	async function copySetupCommand(text: string) {
		await navigator.clipboard.writeText(text);
		setupCopied = true;
		setTimeout(() => (setupCopied = false), 2000);
	}
</script>

<!-- Provider warning -->
{#if noProviders}
	<ProviderStatusBanner
		providerStatus={options.provider_status}
		detectedProvider={options.detected_provider}
		onConfigured={onReloadOptions}
	/>
{/if}

<!-- Agent name -->
{#if mode !== 'hub'}
	<div>
		<label for="agent-name" class="mb-1 block text-[12px] font-medium text-fg-muted">Agent name</label>
		<input
			id="agent-name"
			bind:value={agentName}
			placeholder="my-agent"
			class="w-full max-w-sm border border-edge bg-surface-1 px-3 py-2 font-mono text-[13px] text-fg outline-none transition-[border-color,box-shadow] duration-150 placeholder:text-fg-faint focus:border-accent-primary/40 focus:shadow-[0_0_0_3px_oklch(0.91_0.20_128/0.08)]"
		/>
	</div>
{/if}

<!-- Mode selection -->
<div>
	<h2 class="mb-3 font-mono text-[12px] font-medium uppercase tracking-[0.1em] text-fg-faint">
		Start from
	</h2>
	<div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
		{#each modeCards as card, i}
			<button
				class="card-surface p-5 text-left transition-[background-color,border-color] duration-150 animate-fade-in-up hover:bg-surface-2"
				class:bg-surface-2={mode === card.id}
				class:border-accent-primary={mode === card.id}
				class:bg-surface-1={mode !== card.id}
				style="animation-delay: {i * 60}ms"
				aria-pressed={mode === card.id}
				onclick={() => onSelectMode(card.id)}
			>
				<card.icon size={16} class="mb-2 {mode === card.id ? 'text-accent-primary' : 'text-fg-faint'}" />
				<div class="text-[13px] font-semibold text-fg">{card.label}</div>
				<div class="mt-0.5 text-[13px] text-fg-faint">{card.desc}</div>
			</button>
		{/each}
	</div>
</div>

<!-- Template picker -->
{#if mode === 'template'}
	<div>
		<h2 class="mb-3 font-mono text-[12px] font-medium uppercase tracking-[0.1em] text-fg-faint">
			Template
		</h2>
		<div class="grid grid-cols-2 gap-2 sm:grid-cols-4">
			{#each options.templates as tpl}
				<button
					class="border p-3 text-left transition-[background-color,border-color] duration-150 hover:bg-surface-2"
					class:border-accent-primary={selectedTemplate === tpl.name}
					class:bg-surface-1={selectedTemplate !== tpl.name}
					class:bg-surface-2={selectedTemplate === tpl.name}
					class:border-edge={selectedTemplate !== tpl.name}
					aria-pressed={selectedTemplate === tpl.name}
					onclick={() => (selectedTemplate = tpl.name)}
				>
					<div class="font-mono text-[13px] font-medium text-fg">{tpl.name}</div>
					<div class="mt-0.5 text-[13px] text-fg-faint">{tpl.description}</div>
				</button>
			{/each}
		</div>
		<!-- Setup guidance panel (discord, telegram) -->
		{#if templateSetup}
			<div class="mt-4 border-l-2 border-l-info bg-info/5 px-4 py-3">
				<h3 class="font-mono text-[12px] font-medium uppercase tracking-[0.1em] text-fg-muted">
					Setup: {selectedTemplate} bot
				</h3>

				<ol class="mt-2.5 space-y-1.5">
					{#each templateSetup.steps as s, i}
						<li class="flex gap-2 text-[13px] text-fg-muted">
							<span class="font-mono text-fg-faint">{i + 1}.</span>
							<span>{s}</span>
						</li>
					{/each}
				</ol>

				<div class="mt-3">
					<span class="font-mono text-[12px] font-medium uppercase tracking-[0.1em] text-fg-faint">
						Environment variables
					</span>
					<div class="mt-1.5 flex flex-wrap gap-2">
						{#each templateSetup.env_vars as envVar}
							<span
								class="inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 font-mono text-[11px]
									{envVar.is_set ? 'bg-ok/15 text-ok' : 'bg-warn/15 text-warn'}"
							>
								{envVar.name}
								<span class="text-[10px]">{envVar.is_set ? 'set' : 'not set'}</span>
							</span>
						{/each}
					</div>
				</div>

				{#if templateSetup.extras.length > 0}
					<div class="mt-3">
						<span class="font-mono text-[12px] font-medium uppercase tracking-[0.1em] text-fg-faint">
							Install dependency
						</span>
						<div class="mt-1.5 flex items-center justify-between border border-edge bg-surface-1 px-3 py-2">
							<code class="font-mono text-[13px] text-fg-muted">uv sync --extra {templateSetup.extras[0]}</code>
							<button
								class="ml-3 shrink-0 text-fg-faint transition-[color] duration-150 hover:text-fg-muted"
								onclick={() => copySetupCommand(`uv sync --extra ${templateSetup?.extras[0]}`)}
								aria-label="Copy install command"
							>
								{#if setupCopied}
									<Check size={14} class="text-ok" />
								{:else}
									<Copy size={14} />
								{/if}
							</button>
						</div>
					</div>
				{/if}

				<div class="mt-3">
					<a
						href={templateSetup.docs_url}
						target="_blank"
						rel="noopener"
						class="inline-flex items-center gap-1 text-[13px] text-accent-primary transition-[color] duration-150 hover:text-accent-primary-hover"
					>
						Full setup guide
						<ExternalLink size={12} />
					</a>
				</div>
			</div>
		{/if}

		<!-- Bridge hint to Describe mode -->
		<p class="mt-3 flex items-start gap-1.5 text-[12px] text-fg-faint">
			<Sparkles size={12} class="mt-0.5 shrink-0" />
			<span>
				Need to combine features like memory, RAG, and triggers?
				<button class="text-accent-primary hover:underline" onclick={() => onSelectMode('description')}>
					Use Describe
				</button>
				to compose with AI.
			</span>
		</p>
	</div>
{/if}

<!-- Description input -->
{#if mode === 'description'}
	<div>
		<h2 class="mb-3 font-mono text-[12px] font-medium uppercase tracking-[0.1em] text-fg-faint">
			Describe your agent
		</h2>
		<textarea
			bind:value={description}
			placeholder="A code review agent that checks for bugs and style issues..."
			class="w-full resize-none border border-edge bg-surface-1 p-3 font-mono text-[13px] text-fg outline-none transition-[border-color,box-shadow] duration-150 placeholder:text-fg-faint focus:border-accent-primary/40 focus:shadow-[0_0_0_3px_oklch(0.91_0.20_128/0.08)]"
			style="min-height: 100px"
			disabled={generating}
		></textarea>
	</div>
{/if}

<!-- LangChain source input -->
{#if mode === 'langchain'}
	<div>
		<h2 class="mb-3 font-mono text-[12px] font-medium uppercase tracking-[0.1em] text-fg-faint">
			LangChain source
		</h2>
		<textarea
			bind:value={langchainSource}
			placeholder={"from langchain.agents import create_agent\nfrom langchain.tools import tool\n\n@tool\ndef my_tool(query: str) -> str:\n    ..."}
			class="w-full resize-none border border-edge bg-surface-1 p-3 font-mono text-[13px] text-fg outline-none transition-[border-color,box-shadow] duration-150 placeholder:text-fg-faint focus:border-accent-primary/40 focus:shadow-[0_0_0_3px_oklch(0.91_0.20_128/0.08)]"
			style="min-height: 200px"
			disabled={generating}
		></textarea>
	</div>
{/if}

<!-- Hub search -->
{#if mode === 'hub'}
	<HubSearchPanel
		bind:hubQuery
		{hubResults}
		{hubSearching}
		{hubError}
		bind:selectedHubRef
		{hubFeaturedResults}
		{hubFeaturedLoading}
		onQueryInput={onHubQueryInput}
		onSelectResult={onHubSelectResult}
	/>
{/if}

<!-- Provider / Model -->
{#if mode}
	<ModelSelector
		providers={options.providers}
		customPresets={options.custom_presets}
		ollamaModels={options.ollama_models}
		ollamaBaseUrl={options.ollama_base_url}
		bind:selectedProvider
		bind:selectedModel
		bind:customModelName
		bind:customBaseUrl
		bind:apiKey
		hint={mode === 'langchain'
			? 'Used by the builder to generate YAML. Your agent\u2019s model comes from the source code.'
			: 'Powers the agent and generates the role YAML. You can change it later.'}
	/>

	<!-- Generate button -->
	<div>
		<button
			class="flex items-center gap-2 rounded-full bg-accent-primary px-6 py-2.5 text-[13px] font-medium text-surface-0 transition-[background-color,box-shadow] duration-150 hover:bg-accent-primary-hover hover:shadow-[0_0_16px_oklch(0.91_0.20_128/0.25)] disabled:opacity-40"
			disabled={!canGenerate() || generating}
			onclick={onGenerate}
		>
			{#if generating}
				<Loader2 size={14} class="animate-spin" />
				{mode === 'hub' ? 'Loading...' : 'Generating...'}
			{:else}
				{generateButtonLabel}
			{/if}
		</button>

		{#if generateError}
			<div class="mt-3 border-l-2 border-l-fail bg-fail/5 px-3 py-2">
				<p class="text-[13px] text-fail">{generateError}</p>
			</div>
		{/if}
	</div>
{/if}
