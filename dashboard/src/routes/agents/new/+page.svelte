<script lang="ts">
	import { onMount } from 'svelte';
	import {
		getBuilderOptions,
		seedAgent,
		saveAgent,
		hubSearch,
		hubSeed,
		hubFeatured,
		type BuilderOptions,
		type ValidationIssue,
		type EmbeddingWarning,
		type SaveResult,
		type HubSearchResult
	} from '$lib/api/builder';
	import { saveProviderKey } from '$lib/api/providers';
	import { ApiError } from '$lib/api/client';
	import { page } from '$app/state';
	import { Skeleton } from '$lib/components/ui/skeleton';
	import LoadError from '$lib/components/ui/LoadError.svelte';
	import ConfigureScreen from '$lib/components/agents/ConfigureScreen.svelte';
	import EditorScreen from '$lib/components/agents/EditorScreen.svelte';
	import SuccessScreen from '$lib/components/agents/SuccessScreen.svelte';
	import { ArrowLeft } from 'lucide-svelte';
	import { setCrumbs } from '$lib/stores/breadcrumb.svelte';

	$effect(() => { setCrumbs([{ label: 'Agents', href: '/agents' }, { label: 'New Agent' }]); });

	// -- State ----------------------------------------------------------------

	type Mode = 'description' | 'template' | 'blank' | 'hub' | 'import';
	type ImportFramework = 'langchain' | 'pydanticai';
	type Step = 'configure' | 'editor' | 'success';

	let step: Step = $state('configure');
	let mode: Mode | null = $state(null);

	// Options
	let options = $state<BuilderOptions | null>(null);
	let optionsLoading = $state(true);
	let optionsError: string | null = $state(null);

	// Configure form state
	let selectedTemplate: string | null = $state(null);
	let agentName = $state('');
	let description = $state('');
	let selectedProvider = $state('');
	let selectedModel = $state('');
	let customModelName = $state('');
	let customBaseUrl = $state('');
	let apiKey = $state('');
	let langchainSource = $state('');
	let pydanticaiSource = $state('');
	let importFramework: ImportFramework = $state('langchain');
	let generating = $state(false);
	let generateError: string | null = $state(null);

	// Hub state (page-owned to survive mount/unmount)
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

	// Editor / cross-step state
	let yamlText = $state('');
	let explanation = $state('');
	let issues: ValidationIssue[] = $state([]);
	let embeddingWarning: EmbeddingWarning | null = $state(null);
	let sidecarSource: string | null = $state(null);
	let importWarnings: string[] = $state([]);

	// Save state
	let selectedDir = $state('');
	let filename = $state('role.yaml');
	let saving = $state(false);
	let saveError: string | null = $state(null);
	let showOverwrite = $state(false);

	// Success state
	let saveResult: SaveResult | null = $state(null);

	// Starter state (from ?starter= URL param)
	let pendingStarter: string | null = $state(null);

	// -- Derived --------------------------------------------------------------

	const noProviders = $derived(
		options !== null &&
		!options.detected_provider &&
		(options.provider_status ?? []).every((p) => !p.is_configured)
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
		if (mode !== 'hub' && !agentName.trim()) return false;
		if (mode === 'template' && !selectedTemplate) return false;
		if (mode === 'description' && !description.trim()) return false;
		if (mode === 'import') {
			const src = importFramework === 'langchain' ? langchainSource : pydanticaiSource;
			if (!src.trim()) return false;
		}
		if (mode === 'hub' && !selectedHubRef) return false;
		if (isCustomEndpoint && !customModelName.trim()) return false;
		if (selectedProvider === 'custom' && !customBaseUrl.trim()) return false;
		if (isCustomEndpoint && activePreset && !activePreset.key_configured && !apiKey.trim()) return false;
		return true;
	});

	const generateButtonLabel = $derived(
		mode === 'hub' ? 'Load from Hub' : mode === 'import' ? 'Import' : 'Generate'
	);

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

			// Handle ?starter= URL param
			const starterSlug = page.url.searchParams.get('starter');
			if (starterSlug) {
				if (options.detected_provider) {
					generating = true;
					try {
						const result = await seedAgent({
							mode: 'starter',
							name: starterSlug,
							starter_slug: starterSlug,
							provider: options.detected_provider,
							model: options.detected_model ?? undefined
						});
						yamlText = result.yaml_text;
						explanation = result.explanation;
						issues = result.issues;
						embeddingWarning = result.embedding_warning;
						agentName = starterSlug;
						mode = 'template';
						step = 'editor';
						filename = `${starterSlug}.yaml`;
					} catch (e) {
						generateError = e instanceof ApiError ? e.detail : String(e);
					} finally {
						generating = false;
					}
				} else {
					pendingStarter = starterSlug;
					agentName = starterSlug;
					mode = 'template';
				}
			}
		} catch {
			optionsError = 'Could not load builder options.';
		} finally {
			optionsLoading = false;
		}
	});

	async function reloadOptions() {
		try {
			options = await getBuilderOptions();
			if (options.detected_provider) {
				selectedProvider = options.detected_provider;
				selectedModel = options.detected_model ?? '';
			}
		} catch {
			// best effort
		}
	}

	// -- Actions --------------------------------------------------------------

	function selectMode(m: Mode) {
		mode = m;
		generateError = null;
		pendingStarter = null;
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

	async function handleGenerate() {
		if (!canGenerate() || generating) return;
		generating = true;
		generateError = null;

		try {
			let resolvedApiKeyEnv: string | undefined;
			if (apiKey.trim() && isCustomEndpoint) {
				const keyResult = await saveProviderKey({
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
			} else if (pendingStarter) {
				result = await seedAgent({
					mode: 'starter',
					name: agentName.trim(),
					starter_slug: pendingStarter,
					provider: selectedProvider,
					model: (isCustomEndpoint ? customModelName.trim() : selectedModel) || undefined,
					base_url: customBaseUrl || undefined,
					api_key_env: resolvedApiKeyEnv
				});
				pendingStarter = null;
			} else {
				result = await seedAgent({
					mode: mode === 'import' ? importFramework : mode!,
					name: agentName.trim(),
					template: mode === 'template' ? selectedTemplate! : undefined,
					description: mode === 'description' ? description.trim() : undefined,
					langchain_source: mode === 'import' && importFramework === 'langchain' ? langchainSource : undefined,
					pydanticai_source: mode === 'import' && importFramework === 'pydanticai' ? pydanticaiSource : undefined,
					provider: selectedProvider,
					model: (isCustomEndpoint ? customModelName.trim() : selectedModel) || undefined,
					base_url: customBaseUrl || undefined,
					api_key_env: resolvedApiKeyEnv
				});
			}
			yamlText = result.yaml_text;
			explanation = result.explanation;
			issues = result.issues;
			embeddingWarning = result.embedding_warning;
			sidecarSource = result.sidecar_source ?? null;
			importWarnings = result.import_warnings ?? [];
			if (mode !== 'hub' && agentName.trim()) {
				const slug = agentName.trim().toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
				filename = slug ? `${slug}.yaml` : 'role.yaml';
			}
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

	async function handleSave(force = false) {
		saving = true;
		saveError = null;
		showOverwrite = false;

		try {
			saveResult = await saveAgent({
				yaml_text: yamlText,
				directory: selectedDir,
				filename: filename,
				force,
				sidecar_source: sidecarSource ?? undefined
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
		agentName = '';
		selectedTemplate = null;
		description = '';
		yamlText = '';
		explanation = '';
		issues = [];
		embeddingWarning = null;
		sidecarSource = null;
		importWarnings = [];
		langchainSource = '';
		pydanticaiSource = '';
		importFramework = 'langchain';
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
		<h1 class="text-2xl font-semibold tracking-[-0.03em] text-fg">New Agent</h1>
	</div>

	{#if optionsLoading}
		<Skeleton class="h-24 bg-surface-1" />
		<Skeleton class="h-40 bg-surface-1" />
	{:else if optionsError}
		<LoadError message={optionsError} onRetry={() => location.reload()} />

	{:else if step === 'configure' && options}
		<ConfigureScreen
			{options}
			bind:mode
			bind:agentName
			bind:description
			bind:langchainSource
			bind:pydanticaiSource
			bind:importFramework
			bind:selectedTemplate
			bind:selectedProvider
			bind:selectedModel
			bind:customModelName
			bind:customBaseUrl
			bind:apiKey
			bind:hubQuery
			{hubResults}
			{hubSearching}
			{hubError}
			bind:selectedHubRef
			{hubFeaturedResults}
			{hubFeaturedLoading}
			onHubQueryInput={handleHubQueryInput}
			onHubSelectResult={selectHubResult}
			{generating}
			{generateError}
			{canGenerate}
			{generateButtonLabel}
			{noProviders}
			onGenerate={handleGenerate}
			onReloadOptions={reloadOptions}
			onSelectMode={selectMode}
		/>

	{:else if step === 'editor'}
		<EditorScreen
			bind:yamlText
			{explanation}
			roleDirs={options?.role_dirs ?? []}
			bind:selectedDir
			bind:filename
			bind:issues
			bind:embeddingWarning
			{importWarnings}
			{saving}
			{saveError}
			{showOverwrite}
			onSave={() => handleSave()}
			onSaveForce={() => handleSave(true)}
			onBack={goBack}
			toolFuncMap={options?.tool_func_map ?? {}}
		/>

	{:else if step === 'success' && saveResult}
		<SuccessScreen
			{saveResult}
			onCreateAnother={createAnother}
		/>
	{/if}
</div>
