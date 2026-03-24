<script lang="ts">
	import { onMount } from 'svelte';
	import {
		getBuilderOptions,
		seedAgent,
		saveKey,
		validateYaml,
		saveAgent,
		hubSearch,
		hubSeed,
		hubFeatured,
		type BuilderOptions,
		type ValidationIssue,
		type SaveResult,
		type HubSearchResult
	} from '$lib/api/builder';
	import { ApiError } from '$lib/api/client';
	import { Skeleton } from '$lib/components/ui/skeleton';
	import CognitionPanel from '$lib/components/agents/CognitionPanel.svelte';
	import ModelSelector from '$lib/components/ui/ModelSelector.svelte';
	import {
		ArrowLeft,
		LayoutTemplate,
		Sparkles,
		FileCode,
		Globe,
		Search,
		Loader2,
		CircleX,
		TriangleAlert,
		CheckCircle,
		Copy,
		Check,
		Download,
		Info,
		ExternalLink,
		Brain
	} from 'lucide-svelte';

	// -- State ----------------------------------------------------------------

	type Mode = 'description' | 'template' | 'blank' | 'hub';
	type Step = 'configure' | 'editor' | 'success';

	let step: Step = $state('configure');
	let mode: Mode | null = $state(null);

	// Configure state
	let options = $state<BuilderOptions | null>(null);
	let optionsLoading = $state(true);
	let optionsError: string | null = $state(null);
	let selectedTemplate: string | null = $state(null);
	let description = $state('');
	let selectedProvider = $state('');
	let selectedModel = $state('');
	let customModelName = $state('');
	let customBaseUrl = $state('');
	let apiKey = $state('');
	let generating = $state(false);
	let generateError: string | null = $state(null);

	// Hub state
	let hubQuery = $state('');
	let hubResults: HubSearchResult[] = $state([]);
	let hubSearching = $state(false);
	let hubError: string | null = $state(null);
	let selectedHubRef: string | null = $state(null);
	let hubSearchSeq = $state(0);
	let hubSearchTimer: ReturnType<typeof setTimeout> | null = $state(null);
	let hubFeaturedResults: HubSearchResult[] = $state([]);
	let hubFeaturedLoading = $state(false);
	let hubFeaturedLoaded = $state(false);

	// Editor state
	let yamlText = $state('');
	let explanation = $state('');
	let issues: ValidationIssue[] = $state([]);
	let validating = $state(false);
	let validateTimer: ReturnType<typeof setTimeout> | null = $state(null);
	let cognitionOpen = $state(false);

	// Save state
	let selectedDir = $state('');
	let filename = $state('role.yaml');
	let saving = $state(false);
	let saveError: string | null = $state(null);
	let showOverwrite = $state(false);

	// Success state
	let saveResult: SaveResult | null = $state(null);
	let copied = $state(false);
	let setupCopied = $state(false);

	// -- Derived --------------------------------------------------------------

	const hasErrors = $derived(issues.some((i) => i.severity === 'error'));

	const templateSetup = $derived(
		(selectedTemplate && options?.template_setups?.[selectedTemplate]) || null
	);

	const customPresetNames = $derived(
		new Set((options?.custom_presets ?? []).map((p: { name: string }) => p.name))
	);

	const isCustomEndpoint = $derived(customPresetNames.has(selectedProvider));

	const activePreset = $derived(
		(options?.custom_presets ?? []).find((p: { name: string }) => p.name === selectedProvider) ?? null
	);

	const canGenerate = $derived(() => {
		if (!mode || !selectedProvider) return false;
		if (mode === 'template' && !selectedTemplate) return false;
		if (mode === 'description' && !description.trim()) return false;
		if (mode === 'hub' && !selectedHubRef) return false;
		if (isCustomEndpoint && !customModelName.trim()) return false;
		if (selectedProvider === 'custom' && !customBaseUrl.trim()) return false;
		// For presets without configured key, require key input
		if (isCustomEndpoint && activePreset && !activePreset.key_configured && !apiKey.trim()) return false;
		return true;
	});

	const generateButtonLabel = $derived(mode === 'hub' ? 'Load from Hub' : 'Generate');

	// -- Load options ---------------------------------------------------------

	onMount(async () => {
		try {
			options = await getBuilderOptions();
			if (options.detected_provider) {
				selectedProvider = options.detected_provider;
				selectedModel = options.detected_model ?? '';
			} else if (options.providers.length > 0) {
				selectedProvider = options.providers[0].provider;
				selectedModel = options.providers[0].models[0]?.name ?? '';
			}
			if (options.role_dirs.length > 0) {
				selectedDir = options.role_dirs[0];
			}
		} catch {
			optionsError = 'Could not load builder options.';
		} finally {
			optionsLoading = false;
		}
	});

	// -- Actions --------------------------------------------------------------

	function selectMode(m: Mode) {
		mode = m;
		generateError = null;
		if (m === 'blank') {
			selectedTemplate = null;
		}
		if (m === 'hub') {
			loadHubFeatured();
		}
	}

	async function loadHubFeatured() {
		if (hubFeaturedLoaded || hubFeaturedLoading) return;
		hubFeaturedLoading = true;
		try {
			const result = await hubFeatured();
			hubFeaturedResults = result.items;
		} catch {
			// Featured is best-effort -- silently degrade
		} finally {
			hubFeaturedLoading = false;
			hubFeaturedLoaded = true;
		}
	}

	// -- Hub search -----------------------------------------------------------

	function handleHubQueryInput() {
		if (hubSearchTimer) clearTimeout(hubSearchTimer);
		hubError = null;

		if (hubQuery.trim().length < 2) {
			hubResults = [];
			hubSearching = false;
			return;
		}

		hubSearchTimer = setTimeout(async () => {
			const seq = ++hubSearchSeq;
			hubSearching = true;
			try {
				const result = await hubSearch(hubQuery.trim());
				// Discard stale responses
				if (seq !== hubSearchSeq) return;
				hubResults = result.items;
			} catch (e) {
				if (seq !== hubSearchSeq) return;
				hubError = e instanceof ApiError ? e.detail : String(e);
			} finally {
				if (seq === hubSearchSeq) hubSearching = false;
			}
		}, 300);
	}

	function selectHubResult(result: HubSearchResult) {
		const version = result.latest_version || 'latest';
		selectedHubRef = `${result.owner}/${result.name}@${version}`;
	}

	// -- Generate / Load ------------------------------------------------------

	async function handleGenerate() {
		if (!canGenerate() || generating) return;
		generating = true;
		generateError = null;

		try {
			// Save API key first if provided
			let resolvedApiKeyEnv: string | undefined;
			if (apiKey.trim() && isCustomEndpoint) {
				const keyResult = await saveKey({
					preset: activePreset?.name !== 'custom' ? activePreset?.name : undefined,
					base_url: selectedProvider === 'custom' ? customBaseUrl : undefined,
					api_key: apiKey.trim()
				});
				resolvedApiKeyEnv = keyResult.env_var;
			} else if (activePreset?.key_configured) {
				resolvedApiKeyEnv = activePreset.api_key_env;
			}

			let result;
			if (mode === 'hub') {
				result = await hubSeed({
					ref: selectedHubRef!,
					provider: selectedProvider,
					model: (isCustomEndpoint ? customModelName.trim() : selectedModel) || undefined,
					base_url: customBaseUrl || undefined,
					api_key_env: resolvedApiKeyEnv
				});
			} else {
				result = await seedAgent({
					mode: mode!,
					template: mode === 'template' ? selectedTemplate! : undefined,
					description: mode === 'description' ? description.trim() : undefined,
					provider: selectedProvider,
					model: (isCustomEndpoint ? customModelName.trim() : selectedModel) || undefined,
					base_url: customBaseUrl || undefined,
					api_key_env: resolvedApiKeyEnv
				});
			}
			yamlText = result.yaml_text;
			explanation = result.explanation;
			issues = result.issues;
			step = 'editor';
		} catch (e) {
			if (e instanceof ApiError) {
				generateError = e.detail;
			} else {
				generateError = String(e);
			}
		} finally {
			generating = false;
		}
	}

	function handleYamlInput() {
		if (validateTimer) clearTimeout(validateTimer);
		validateTimer = setTimeout(async () => {
			if (!yamlText.trim()) {
				issues = [];
				return;
			}
			validating = true;
			try {
				const result = await validateYaml(yamlText);
				issues = result.issues;
			} catch {
				// skip
			} finally {
				validating = false;
			}
		}, 500);
	}

	async function handleSave(force = false) {
		saving = true;
		saveError = null;
		showOverwrite = false;

		try {
			saveResult = await saveAgent({
				yaml_text: yamlText,
				directory: selectedDir,
				filename: filename,
				force
			});
			step = 'success';
		} catch (e) {
			if (e instanceof ApiError) {
				if (e.status === 409) {
					showOverwrite = true;
					saveError = null;
				} else {
					saveError = e.detail;
				}
			} else {
				saveError = String(e);
			}
		} finally {
			saving = false;
		}
	}

	function goBack() {
		step = 'configure';
		saveError = null;
		showOverwrite = false;
	}

	function createAnother() {
		step = 'configure';
		mode = null;
		selectedTemplate = null;
		description = '';
		yamlText = '';
		explanation = '';
		issues = [];
		saveResult = null;
		saveError = null;
		showOverwrite = false;
		filename = 'role.yaml';
		customModelName = '';
		customBaseUrl = '';
		apiKey = '';
		hubQuery = '';
		hubResults = [];
		hubError = null;
		selectedHubRef = null;
		hubSearchSeq = 0;
	}

	async function copyCommand(text: string) {
		await navigator.clipboard.writeText(text);
		copied = true;
		setTimeout(() => (copied = false), 2000);
	}

	async function copySetupCommand(text: string) {
		await navigator.clipboard.writeText(text);
		setupCopied = true;
		setTimeout(() => (setupCopied = false), 2000);
	}

	const modeCards: { id: Mode; label: string; desc: string; icon: typeof LayoutTemplate }[] = [
		{ id: 'description', label: 'Describe', desc: 'AI generates YAML', icon: Sparkles },
		{ id: 'template', label: 'Template', desc: 'Start from a preset', icon: LayoutTemplate },
		{ id: 'blank', label: 'Blank', desc: 'Minimal skeleton', icon: FileCode },
		{ id: 'hub', label: 'InitHub', desc: 'Browse hub.initrunner.ai', icon: Globe }
	];
</script>

<div class="space-y-6">
	<!-- Header -->
	<div class="flex items-center gap-4">
		{#if step === 'editor'}
			<button
				class="inline-flex items-center gap-1.5 text-[13px] text-fg-faint transition-[color] duration-150 hover:text-fg-muted"
				onclick={goBack}
			>
				<ArrowLeft size={14} />
				Back
			</button>
		{:else}
			<a
				href="/agents"
				class="inline-flex items-center gap-1.5 text-[13px] text-fg-faint transition-[color] duration-150 hover:text-fg-muted"
			>
				<ArrowLeft size={14} />
				Agents
			</a>
		{/if}
		<h1 class="text-xl font-semibold tracking-[-0.02em] text-fg">New Agent</h1>
	</div>

	{#if optionsLoading}
		<Skeleton class="h-24 bg-surface-1" />
		<Skeleton class="h-40 bg-surface-1" />
	{:else if optionsError}
		<div class="border border-fail/20 bg-fail/5 px-4 py-3">
			<p class="text-[13px] text-fail">{optionsError}</p>
			<button
				class="mt-2 text-[13px] text-fg-faint underline transition-[color] duration-150 hover:text-fg-muted"
				onclick={() => location.reload()}
			>
				Retry
			</button>
		</div>

	<!-- ============================================================ -->
	<!-- CONFIGURE SCREEN                                             -->
	<!-- ============================================================ -->
	{:else if step === 'configure'}
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
						onclick={() => selectMode(card.id)}
					>
						<card.icon size={16} class="mb-2 {mode === card.id ? 'text-accent-primary' : 'text-fg-faint'}" />
						<div class="text-[13px] font-semibold text-fg">{card.label}</div>
						<div class="mt-0.5 text-[13px] text-fg-faint">{card.desc}</div>
					</button>
				{/each}
			</div>
		</div>

		<!-- Template picker -->
		{#if mode === 'template' && options}
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
						<button class="text-accent-primary hover:underline" onclick={() => selectMode('description')}>
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

		<!-- Hub search -->
		{#if mode === 'hub'}
			<div>
				<h2 class="mb-3 font-mono text-[12px] font-medium uppercase tracking-[0.1em] text-fg-faint">
					Search InitHub
				</h2>
				<div class="relative">
					<Search size={14} class="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-fg-faint" />
					<input
						type="text"
						bind:value={hubQuery}
						oninput={handleHubQueryInput}
						placeholder="Search for agent packages..."
						class="w-full border border-edge bg-surface-1 py-2 pl-9 pr-3 font-mono text-[13px] text-fg outline-none transition-[border-color,box-shadow] duration-150 placeholder:text-fg-faint focus:border-accent-primary/40 focus:shadow-[0_0_0_3px_oklch(0.91_0.20_128/0.08)]"
					/>
				</div>

				<!-- Hub results -->
				<div class="mt-3">
					{#if hubSearching}
						<div class="flex items-center gap-2 py-6 justify-center text-fg-faint">
							<Loader2 size={14} class="animate-spin" />
							<span class="text-[13px]">Searching...</span>
						</div>
					{:else if hubError}
						<div class="border-l-2 border-l-fail bg-fail/5 px-3 py-2">
							<p class="text-[13px] text-fail">{hubError}</p>
						</div>
					{:else if hubQuery.trim().length >= 2 && hubResults.length === 0}
						<p class="py-6 text-center text-[13px] text-fg-faint">
							No packages found for '{hubQuery}'.
						</p>
					{:else if hubResults.length > 0}
						<div class="grid grid-cols-1 gap-2 sm:grid-cols-2">
							{#each hubResults as result}
								{@const ref = `${result.owner}/${result.name}@${result.latest_version || 'latest'}`}
								<button
									class="border p-3 text-left transition-[background-color,border-color] duration-150 hover:bg-surface-2"
									class:border-accent-primary={selectedHubRef === ref}
									class:bg-surface-2={selectedHubRef === ref}
									class:bg-surface-1={selectedHubRef !== ref}
									class:border-edge={selectedHubRef !== ref}
									aria-pressed={selectedHubRef === ref}
									onclick={() => selectHubResult(result)}
								>
									<div class="font-mono text-[13px] font-medium text-fg">
										{result.owner}/{result.name}
									</div>
									<div class="mt-1 line-clamp-2 text-[13px] text-fg-faint">
										{result.description}
									</div>
									<div class="mt-2 flex flex-wrap items-center gap-2">
										{#if result.latest_version}
											<span class="rounded-full bg-surface-3 px-2 py-0.5 font-mono text-[11px] text-fg-muted">
												v{result.latest_version}
											</span>
										{/if}
										<span class="flex items-center gap-1 font-mono text-[11px] text-fg-faint">
											<Download size={10} />
											{result.downloads}
										</span>
										{#each result.tags.slice(0, 3) as tag}
											<span class="rounded-full border border-edge px-2 py-0.5 font-mono text-[11px] text-fg-faint">
												{tag}
											</span>
										{/each}
									</div>
								</button>
							{/each}
						</div>
					{:else}
						<!-- Featured packages (shown when no search query) -->
						{#if hubFeaturedLoading}
							<div class="grid grid-cols-1 gap-2 sm:grid-cols-2">
								{#each Array(4) as _}
									<Skeleton class="h-24 bg-surface-1" />
								{/each}
							</div>
						{:else if hubFeaturedResults.length > 0}
							<div class="mb-2 flex items-center justify-between">
								<span class="font-mono text-[12px] font-medium uppercase tracking-[0.1em] text-fg-faint">
									Popular on InitHub
								</span>
								<a
									href="https://hub.initrunner.ai"
									target="_blank"
									rel="noopener"
									class="inline-flex items-center gap-1 text-[13px] text-accent-primary transition-[color] duration-150 hover:text-accent-primary-hover"
								>
									View all
									<ExternalLink size={12} />
								</a>
							</div>
							<div class="grid grid-cols-1 gap-2 sm:grid-cols-2">
								{#each hubFeaturedResults.slice(0, 8) as result, i}
									{@const ref = `${result.owner}/${result.name}@${result.latest_version || 'latest'}`}
									<button
										class="border p-3 text-left transition-[background-color,border-color] duration-150 animate-fade-in-up hover:bg-surface-2"
										class:border-accent-primary={selectedHubRef === ref}
										class:bg-surface-2={selectedHubRef === ref}
										class:bg-surface-1={selectedHubRef !== ref}
										class:border-edge={selectedHubRef !== ref}
										style="animation-delay: {i * 60}ms"
										aria-pressed={selectedHubRef === ref}
										onclick={() => selectHubResult(result)}
									>
										<div class="font-mono text-[13px] font-medium text-fg">
											{result.owner}/{result.name}
										</div>
										<div class="mt-1 line-clamp-2 text-[13px] text-fg-faint">
											{result.description}
										</div>
										<div class="mt-2 flex flex-wrap items-center gap-2">
											{#if result.latest_version}
												<span class="rounded-full bg-surface-3 px-2 py-0.5 font-mono text-[11px] text-fg-muted">
													v{result.latest_version}
												</span>
											{/if}
											<span class="flex items-center gap-1 font-mono text-[11px] text-fg-faint">
												<Download size={10} />
												{result.downloads}
											</span>
											{#each result.tags.slice(0, 3) as tag}
												<span class="rounded-full border border-edge px-2 py-0.5 font-mono text-[11px] text-fg-faint">
													{tag}
												</span>
											{/each}
										</div>
									</button>
								{/each}
							</div>
						{:else}
							<p class="py-6 text-center text-[13px] text-fg-faint">
								Search for agent packages on InitHub
							</p>
						{/if}
					{/if}
				</div>

				<!-- CLI install hint -->
				<p class="mt-3 flex items-start gap-1.5 text-[12px] text-accent-primary/70">
					<Info size={12} class="mt-0.5 shrink-0" />
					<span>
						Dashboard loads the primary role YAML only. For complete packages with all bundled files, run
						<code class="font-mono text-accent-primary">initrunner install owner/name</code>.
					</span>
				</p>
			</div>
		{/if}

		<!-- Provider / Model -->
		{#if mode && options}
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
			/>

			<!-- Generate button -->
			<div>
				<button
					class="flex items-center gap-2 rounded-full bg-accent-primary px-6 py-2.5 text-[13px] font-medium text-surface-0 transition-[background-color,box-shadow] duration-150 hover:bg-accent-primary-hover hover:shadow-[0_0_16px_oklch(0.91_0.20_128/0.25)] disabled:opacity-40"
					disabled={!canGenerate() || generating}
					onclick={handleGenerate}
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

	<!-- ============================================================ -->
	<!-- EDITOR SCREEN                                                -->
	<!-- ============================================================ -->
	{:else if step === 'editor'}
		{#if explanation}
			<div class="border-l-2 border-l-info bg-info/5 px-3 py-2">
				<p class="text-[13px] text-fg-muted">{explanation}</p>
			</div>
		{/if}

		<!-- Toolbar -->
		<div class="flex items-center justify-end">
			<button
				class="flex items-center gap-1.5 px-3 py-1.5 font-mono text-[12px] transition-[color,background-color,border-color] duration-150 border
					{cognitionOpen
						? 'border-accent-primary/30 bg-accent-primary/10 text-accent-primary'
						: 'border-accent-primary/20 bg-accent-primary/[0.06] text-accent-primary/70 hover:bg-accent-primary/10 hover:text-accent-primary'}"
				onclick={() => (cognitionOpen = !cognitionOpen)}
				aria-pressed={cognitionOpen}
			>
				<Brain size={13} strokeWidth={1.5} />
				Cognition
			</button>
		</div>

		<!-- Editor + Cognition panel -->
		<div class="flex gap-4">
			<!-- YAML editor column -->
			<div class="min-w-0 flex-1 space-y-0">
				<textarea
					bind:value={yamlText}
					oninput={handleYamlInput}
					class="w-full resize-y border border-edge bg-surface-0 p-4 font-mono text-[13px] leading-relaxed text-fg-muted outline-none transition-[border-color,box-shadow] duration-150 focus:border-accent-primary/40 focus:shadow-[0_0_0_3px_oklch(0.91_0.20_128/0.08)]"
					style="min-height: 400px"
					spellcheck="false"
					aria-label="Role YAML editor"
				></textarea>

				{#if issues.length > 0}
					<div class="space-y-1" role="alert">
						{#each issues as issue}
							<div
								class="flex items-start gap-2 px-3 py-1.5 {issue.severity === 'error' ? 'bg-fail/5' : issue.severity === 'warning' ? 'bg-warn/5' : ''}"
							>
								{#if issue.severity === 'error'}
									<CircleX size={13} class="mt-0.5 shrink-0 text-fail" />
								{:else if issue.severity === 'warning'}
									<TriangleAlert size={13} class="mt-0.5 shrink-0 text-warn" />
								{:else}
									<Info size={13} class="mt-0.5 shrink-0 text-fg-faint" />
								{/if}
								<span class="font-mono text-[13px]" class:text-fail={issue.severity === 'error'} class:text-warn={issue.severity === 'warning'} class:text-fg-faint={issue.severity === 'info'}>
									{issue.field}: {issue.message}
								</span>
							</div>
						{/each}
					</div>
				{/if}
			</div>

			<!-- Cognition panel column -->
			{#if cognitionOpen}
				<div class="w-72 shrink-0 border border-edge bg-surface-0 p-4">
					<CognitionPanel
						{yamlText}
						onUpdate={(newYaml) => {
							yamlText = newYaml;
							handleYamlInput();
						}}
					/>
				</div>
			{/if}
		</div>

		<div>
			<h2 class="mb-3 font-mono text-[12px] font-medium uppercase tracking-[0.1em] text-fg-faint">
				Save to
			</h2>
			<div class="flex items-center gap-2">
				<select
					class="border border-edge bg-surface-1 px-3 py-2 font-mono text-[13px] text-fg outline-none"
					bind:value={selectedDir}
				>
					{#each options?.role_dirs ?? [] as dir}
						<option value={dir}>{dir}</option>
					{/each}
				</select>
				<span class="text-fg-faint">/</span>
				<input
					type="text"
					bind:value={filename}
					class="min-w-0 flex-1 border border-edge bg-surface-1 px-3 py-2 font-mono text-[13px] text-fg outline-none transition-[border-color,box-shadow] duration-150 focus:border-accent-primary/40 focus:shadow-[0_0_0_3px_oklch(0.91_0.20_128/0.08)]"
					placeholder="role.yaml"
				/>
			</div>
		</div>

		{#if showOverwrite}
			<div class="flex items-center gap-3 border-l-2 border-l-warn bg-warn/5 px-3 py-2">
				<TriangleAlert size={14} class="shrink-0 text-warn" />
				<span class="flex-1 text-[13px] text-fg-muted">File already exists at {selectedDir}/{filename}</span>
				<button
					class="bg-warn/20 px-3 py-1 text-[13px] font-medium text-warn transition-[background-color] duration-150 hover:bg-warn/30"
					onclick={() => handleSave(true)}
				>
					Overwrite
				</button>
			</div>
		{/if}

		{#if saveError}
			<div class="border-l-2 border-l-fail bg-fail/5 px-3 py-2">
				<p class="text-[13px] text-fail">{saveError}</p>
			</div>
		{/if}

		<div class="flex gap-3">
			<button
				class="rounded-full border border-edge bg-surface-1 px-5 py-2 text-[13px] font-medium text-fg-muted transition-[color,background-color,border-color] duration-150 hover:bg-surface-2 hover:text-fg hover:border-accent-primary/20"
				onclick={goBack}
			>
				Back
			</button>
			<button
				class="flex items-center gap-2 rounded-full bg-accent-primary px-6 py-2.5 text-[13px] font-medium text-surface-0 transition-[background-color,box-shadow] duration-150 hover:bg-accent-primary-hover hover:shadow-[0_0_16px_oklch(0.91_0.20_128/0.25)] disabled:opacity-40"
				disabled={hasErrors || saving || !yamlText.trim() || !filename.trim()}
				onclick={() => handleSave()}
			>
				{#if saving}
					<Loader2 size={14} class="animate-spin" />
					Saving...
				{:else}
					Save Agent
				{/if}
			</button>
		</div>

	<!-- ============================================================ -->
	<!-- SUCCESS SCREEN                                               -->
	<!-- ============================================================ -->
	{:else if step === 'success' && saveResult}
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
					onclick={createAnother}
				>
					Create Another
				</button>
			</div>
		</div>
	{/if}
</div>
