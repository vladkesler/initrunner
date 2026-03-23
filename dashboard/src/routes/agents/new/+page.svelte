<script lang="ts">
	import { onMount } from 'svelte';
	import {
		getBuilderOptions,
		seedAgent,
		saveKey,
		validateYaml,
		saveAgent,
		type BuilderOptions,
		type ValidationIssue,
		type SaveResult
	} from '$lib/api/builder';
	import { ApiError } from '$lib/api/client';
	import { Skeleton } from '$lib/components/ui/skeleton';
	import {
		ArrowLeft,
		LayoutTemplate,
		Sparkles,
		FileCode,
		Loader2,
		CircleX,
		TriangleAlert,
		CheckCircle,
		Copy,
		Check
	} from 'lucide-svelte';

	// -- State ----------------------------------------------------------------

	type Mode = 'template' | 'description' | 'blank';
	type Step = 'configure' | 'editor' | 'success';

	let step: Step = $state('configure');
	let mode: Mode | null = $state(null);

	// Configure state
	let options: BuilderOptions | null = $state(null);
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

	// Editor state
	let yamlText = $state('');
	let explanation = $state('');
	let issues: ValidationIssue[] = $state([]);
	let validating = $state(false);
	let validateTimer: ReturnType<typeof setTimeout> | null = $state(null);

	// Save state
	let selectedDir = $state('');
	let filename = $state('role.yaml');
	let saving = $state(false);
	let saveError: string | null = $state(null);
	let showOverwrite = $state(false);

	// Success state
	let saveResult: SaveResult | null = $state(null);
	let copied = $state(false);

	// -- Derived --------------------------------------------------------------

	const hasErrors = $derived(issues.some((i) => i.severity === 'error'));

	const customPresetNames = $derived(
		new Set(options?.custom_presets.map((p) => p.name) ?? [])
	);

	const isCustomEndpoint = $derived(customPresetNames.has(selectedProvider));
	const isOllama = $derived(selectedProvider === 'ollama');

	const activePreset = $derived(
		options?.custom_presets.find((p) => p.name === selectedProvider) ?? null
	);

	// For presets with known base_url, no endpoint field needed
	const showEndpointUrl = $derived(
		isOllama || (isCustomEndpoint && selectedProvider === 'custom')
	);

	// Show API key field for custom endpoints (not ollama)
	const showApiKey = $derived(
		isCustomEndpoint && !(activePreset?.key_configured && !apiKey)
	);

	const cloudProviders = $derived(
		(options?.providers ?? []).filter((p) => p.provider !== 'ollama')
	);

	const ollamaProvider = $derived(
		(options?.providers ?? []).find((p) => p.provider === 'ollama')
	);

	const ollamaModels = $derived(() => {
		if (!options) return [];
		if (options.ollama_models.length > 0) return options.ollama_models;
		return ollamaProvider?.models.map((m) => m.name) ?? [];
	});

	const filteredModels = $derived(() => {
		if (!options || !selectedProvider) return [];
		if (isOllama) return [];
		const p = options.providers.find((p) => p.provider === selectedProvider);
		return p?.models ?? [];
	});

	const canGenerate = $derived(() => {
		if (!mode || !selectedProvider) return false;
		if (mode === 'template' && !selectedTemplate) return false;
		if (mode === 'description' && !description.trim()) return false;
		if (isCustomEndpoint && !customModelName.trim()) return false;
		if (selectedProvider === 'custom' && !customBaseUrl.trim()) return false;
		// For presets without configured key, require key input
		if (isCustomEndpoint && activePreset && !activePreset.key_configured && !apiKey.trim()) return false;
		return true;
	});

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
	}

	function selectProvider(provider: string) {
		selectedProvider = provider;
		apiKey = '';
		customModelName = '';

		if (provider === 'ollama') {
			customBaseUrl = '';
			const models = ollamaModels();
			selectedModel = models[0] ?? '';
		} else if (customPresetNames.has(provider)) {
			customBaseUrl = '';
		} else {
			customBaseUrl = '';
			const p = options?.providers.find((p) => p.provider === provider);
			selectedModel = p?.models[0]?.name ?? '';
		}
	}

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

			const result = await seedAgent({
				mode: mode!,
				template: mode === 'template' ? selectedTemplate! : undefined,
				description: mode === 'description' ? description.trim() : undefined,
				provider: selectedProvider,
				model: (isCustomEndpoint ? customModelName.trim() : selectedModel) || undefined,
				base_url: customBaseUrl || undefined,
				api_key_env: resolvedApiKeyEnv
			});
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
	}

	async function copyCommand(text: string) {
		await navigator.clipboard.writeText(text);
		copied = true;
		setTimeout(() => (copied = false), 2000);
	}

	const modeCards: { id: Mode; label: string; desc: string; icon: typeof LayoutTemplate }[] = [
		{ id: 'template', label: 'Template', desc: 'Start from a preset', icon: LayoutTemplate },
		{ id: 'description', label: 'Describe', desc: 'AI generates YAML', icon: Sparkles },
		{ id: 'blank', label: 'Blank', desc: 'Minimal skeleton', icon: FileCode }
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
		<h1 class="text-lg font-medium text-fg">New Agent</h1>
	</div>

	{#if optionsLoading}
		<Skeleton class="h-24 rounded-sm bg-surface-1" />
		<Skeleton class="h-40 rounded-sm bg-surface-1" />
	{:else if optionsError}
		<div class="rounded-sm border border-fail/20 bg-fail/5 px-4 py-3">
			<p class="text-[13px] text-fail">{optionsError}</p>
			<button
				class="mt-2 text-[12px] text-fg-faint underline transition-[color] duration-150 hover:text-fg-muted"
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
			<h2 class="mb-3 font-mono text-[11px] font-medium uppercase tracking-[0.08em] text-fg-faint">
				Start from
			</h2>
			<div class="grid grid-cols-3 gap-3">
				{#each modeCards as card}
					<button
						class="rounded-sm border bg-surface-1 p-4 text-left transition-[background-color,border-color] duration-150 hover:bg-surface-2"
						class:border-l-2={mode === card.id}
						class:border-l-orange={mode === card.id}
						class:border-edge={mode !== card.id}
						aria-pressed={mode === card.id}
						onclick={() => selectMode(card.id)}
					>
						<card.icon size={16} class="mb-2 text-fg-faint" />
						<div class="text-[13px] font-medium text-fg">{card.label}</div>
						<div class="mt-0.5 text-[11px] text-fg-faint">{card.desc}</div>
					</button>
				{/each}
			</div>
		</div>

		<!-- Template picker -->
		{#if mode === 'template' && options}
			<div>
				<h2 class="mb-3 font-mono text-[11px] font-medium uppercase tracking-[0.08em] text-fg-faint">
					Template
				</h2>
				<div class="grid grid-cols-2 gap-2 sm:grid-cols-4">
					{#each options.templates as tpl}
						<button
							class="rounded-sm border p-3 text-left transition-[background-color,border-color] duration-150 hover:bg-surface-2"
							class:border-orange={selectedTemplate === tpl.name}
							class:bg-surface-1={selectedTemplate !== tpl.name}
							class:bg-surface-2={selectedTemplate === tpl.name}
							class:border-edge={selectedTemplate !== tpl.name}
							aria-pressed={selectedTemplate === tpl.name}
							onclick={() => (selectedTemplate = tpl.name)}
						>
							<div class="font-mono text-[12px] font-medium text-fg">{tpl.name}</div>
							<div class="mt-0.5 text-[11px] text-fg-faint">{tpl.description}</div>
						</button>
					{/each}
				</div>
			</div>
		{/if}

		<!-- Description input -->
		{#if mode === 'description'}
			<div>
				<h2 class="mb-3 font-mono text-[11px] font-medium uppercase tracking-[0.08em] text-fg-faint">
					Describe your agent
				</h2>
				<textarea
					bind:value={description}
					placeholder="A code review agent that checks for bugs and style issues..."
					class="w-full resize-none rounded-sm border border-edge bg-surface-1 p-3 font-mono text-[13px] text-fg outline-none transition-[border-color] duration-150 placeholder:text-fg-faint focus:border-surface-3"
					style="min-height: 100px"
					disabled={generating}
				></textarea>
			</div>
		{/if}

		<!-- Provider / Model -->
		{#if mode}
			<div>
				<h2 class="mb-3 font-mono text-[11px] font-medium uppercase tracking-[0.08em] text-fg-faint">
					Model
				</h2>
				<div class="flex gap-3">
					<!-- Provider select with optgroups -->
					<select
						class="rounded-sm border border-edge bg-surface-1 px-3 py-2 font-mono text-[13px] text-fg outline-none"
						bind:value={selectedProvider}
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
						{#if options && options.custom_presets.length > 0}
							<optgroup label="Custom endpoint">
								{#each options.custom_presets as preset}
									<option value={preset.name}>{preset.label}</option>
								{/each}
							</optgroup>
						{/if}
					</select>

					<!-- Model: dropdown for cloud/ollama, text input for custom -->
					{#if isCustomEndpoint}
						<input
							type="text"
							bind:value={customModelName}
							placeholder={activePreset?.placeholder ?? 'model-name'}
							class="min-w-0 flex-1 rounded-sm border border-edge bg-surface-1 px-3 py-2 font-mono text-[13px] text-fg outline-none transition-[border-color] duration-150 placeholder:text-fg-faint focus:border-surface-3"
						/>
					{:else if isOllama}
						<select
							class="min-w-0 flex-1 rounded-sm border border-edge bg-surface-1 px-3 py-2 font-mono text-[13px] text-fg outline-none"
							bind:value={selectedModel}
						>
							{#each ollamaModels() as m}
								<option value={m}>{m}</option>
							{/each}
						</select>
					{:else}
						<select
							class="min-w-0 flex-1 rounded-sm border border-edge bg-surface-1 px-3 py-2 font-mono text-[13px] text-fg outline-none"
							bind:value={selectedModel}
						>
							{#each filteredModels() as m}
								<option value={m.name}>{m.name} -- {m.description}</option>
							{/each}
						</select>
					{/if}
				</div>
			</div>

			<!-- Endpoint URL (only for ollama and custom, not known presets) -->
			{#if showEndpointUrl}
				<div>
					<h2 class="mb-3 font-mono text-[11px] font-medium uppercase tracking-[0.08em] text-fg-faint">
						Endpoint
					</h2>
					<input
						type="text"
						bind:value={customBaseUrl}
						placeholder={isOllama ? options?.ollama_base_url ?? 'http://localhost:11434/v1' : 'https://...'}
						class="w-full rounded-sm border border-edge bg-surface-1 px-3 py-2 font-mono text-[12px] text-fg outline-none transition-[border-color] duration-150 placeholder:text-fg-faint focus:border-surface-3"
					/>
				</div>
			{/if}

			<!-- API Key (for custom endpoints, not ollama) -->
			{#if isCustomEndpoint}
				<div>
					<h2 class="mb-3 font-mono text-[11px] font-medium uppercase tracking-[0.08em] text-fg-faint">
						API Key
					</h2>
					{#if activePreset?.key_configured && !apiKey}
						<p class="flex items-center gap-1.5 text-[12px] text-ok">
							<CheckCircle size={13} />
							Already configured
						</p>
					{:else}
						<input
							type="password"
							bind:value={apiKey}
							placeholder="Paste your API key"
							class="w-full rounded-sm border border-edge bg-surface-1 px-3 py-2 font-mono text-[12px] text-fg outline-none transition-[border-color] duration-150 placeholder:text-fg-faint focus:border-surface-3"
						/>
						{#if activePreset?.key_configured}
							<p class="mt-1.5 text-[11px] text-fg-faint">
								Leave empty to use the existing key
							</p>
						{/if}
					{/if}
				</div>
			{/if}

			<!-- Generate button -->
			<div>
				<button
					class="flex items-center gap-2 rounded-sm bg-orange px-5 py-2.5 text-[13px] font-medium text-white transition-[background-color] duration-150 hover:bg-orange-hover disabled:opacity-40"
					disabled={!canGenerate() || generating}
					onclick={handleGenerate}
				>
					{#if generating}
						<Loader2 size={14} class="animate-spin" />
						Generating...
					{:else}
						Generate
					{/if}
				</button>

				{#if generateError}
					<div class="mt-3 rounded-sm border-l-2 border-l-fail bg-fail/5 px-3 py-2">
						<p class="text-[12px] text-fail">{generateError}</p>
					</div>
				{/if}
			</div>
		{/if}

	<!-- ============================================================ -->
	<!-- EDITOR SCREEN                                                -->
	<!-- ============================================================ -->
	{:else if step === 'editor'}
		{#if explanation}
			<div class="rounded-sm border-l-2 border-l-info bg-info/5 px-3 py-2">
				<p class="text-[12px] text-fg-muted">{explanation}</p>
			</div>
		{/if}

		<textarea
			bind:value={yamlText}
			oninput={handleYamlInput}
			class="w-full resize-y rounded-sm border border-edge bg-surface-0 p-4 font-mono text-[13px] leading-relaxed text-fg-muted outline-none transition-[border-color] duration-150 focus:border-surface-3"
			style="min-height: 400px"
			spellcheck="false"
			aria-label="Role YAML editor"
		></textarea>

		{#if issues.length > 0}
			<div class="space-y-1" role="alert">
				{#each issues as issue}
					<div
						class="flex items-start gap-2 rounded-sm px-3 py-1.5 {issue.severity === 'error' ? 'bg-fail/5' : 'bg-warn/5'}"
					>
						{#if issue.severity === 'error'}
							<CircleX size={13} class="mt-0.5 shrink-0 text-fail" />
						{:else}
							<TriangleAlert size={13} class="mt-0.5 shrink-0 text-warn" />
						{/if}
						<span class="font-mono text-[11px]" class:text-fail={issue.severity === 'error'} class:text-warn={issue.severity === 'warning'}>
							{issue.field}: {issue.message}
						</span>
					</div>
				{/each}
			</div>
		{/if}

		<div>
			<h2 class="mb-3 font-mono text-[11px] font-medium uppercase tracking-[0.08em] text-fg-faint">
				Save to
			</h2>
			<div class="flex items-center gap-2">
				<select
					class="rounded-sm border border-edge bg-surface-1 px-3 py-2 font-mono text-[12px] text-fg outline-none"
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
					class="min-w-0 flex-1 rounded-sm border border-edge bg-surface-1 px-3 py-2 font-mono text-[12px] text-fg outline-none transition-[border-color] duration-150 focus:border-surface-3"
					placeholder="role.yaml"
				/>
			</div>
		</div>

		{#if showOverwrite}
			<div class="flex items-center gap-3 rounded-sm border-l-2 border-l-warn bg-warn/5 px-3 py-2">
				<TriangleAlert size={14} class="shrink-0 text-warn" />
				<span class="flex-1 text-[12px] text-fg-muted">File already exists at {selectedDir}/{filename}</span>
				<button
					class="rounded-sm bg-warn/20 px-3 py-1 text-[12px] font-medium text-warn transition-[background-color] duration-150 hover:bg-warn/30"
					onclick={() => handleSave(true)}
				>
					Overwrite
				</button>
			</div>
		{/if}

		{#if saveError}
			<div class="rounded-sm border-l-2 border-l-fail bg-fail/5 px-3 py-2">
				<p class="text-[12px] text-fail">{saveError}</p>
			</div>
		{/if}

		<div class="flex gap-3">
			<button
				class="rounded-sm border border-edge bg-surface-1 px-4 py-2 text-[13px] font-medium text-fg-muted transition-[color,background-color] duration-150 hover:bg-surface-2 hover:text-fg"
				onclick={goBack}
			>
				Back
			</button>
			<button
				class="flex items-center gap-2 rounded-sm bg-orange px-5 py-2.5 text-[13px] font-medium text-white transition-[background-color] duration-150 hover:bg-orange-hover disabled:opacity-40"
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
				<h2 class="text-lg font-medium text-fg">Agent created</h2>
			</div>
			<p class="mt-2 font-mono text-[12px] text-fg-muted">{saveResult.path}</p>

			{#if saveResult.issues.length > 0}
				<div class="mt-4 space-y-1">
					{#each saveResult.issues as issue}
						<p class="font-mono text-[11px] text-warn">{issue}</p>
					{/each}
				</div>
			{/if}

			{#if saveResult.next_steps.length > 0}
				<div class="mt-6">
					<h3 class="mb-3 font-mono text-[11px] font-medium uppercase tracking-[0.08em] text-fg-faint">
						Next steps
					</h3>
					<div class="space-y-2">
						{#each saveResult.next_steps as cmd}
							<div class="flex items-center justify-between rounded-sm border border-edge bg-surface-1 px-3 py-2">
								<code class="font-mono text-[12px] text-fg-muted">{cmd}</code>
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
					class="flex items-center gap-2 rounded-sm bg-orange px-5 py-2.5 text-[13px] font-medium text-white transition-[background-color] duration-150 hover:bg-orange-hover"
				>
					View Agent
				</a>
				<button
					class="rounded-sm border border-edge bg-surface-1 px-4 py-2 text-[13px] font-medium text-fg-muted transition-[color,background-color] duration-150 hover:bg-surface-2 hover:text-fg"
					onclick={createAnother}
				>
					Create Another
				</button>
			</div>
		</div>
	{/if}
</div>
