<script lang="ts">
	import { onMount } from 'svelte';
	import { fetchTeamBuilderOptions, seedTeam, validateTeam, saveTeam } from '$lib/api/teams';
	import { saveProviderKey } from '$lib/api/providers';
	import { ApiError } from '$lib/api/client';
	import type { TeamBuilderOptions, ValidationIssue, PersonaSeedEntry } from '$lib/api/types';
	import { toast } from '$lib/stores/toast.svelte';
	import { Skeleton } from '$lib/components/ui/skeleton';
	import LoadError from '$lib/components/ui/LoadError.svelte';
	import ModelSelector from '$lib/components/ui/ModelSelector.svelte';
	import PersonaList, { type PersonaEntry } from '$lib/components/teams/PersonaList.svelte';
	import {
		ArrowLeft,
		Check,
		AlertTriangle,
		Copy,
		Users,
		Loader2,
		CheckCircle,
		CircleX
	} from 'lucide-svelte';

	// -- State ----------------------------------------------------------------

	type Step = 'configure' | 'editor' | 'success';

	let step: Step = $state('configure');
	let options = $state<TeamBuilderOptions | null>(null);
	let optionsLoading = $state(true);
	let optionsError: string | null = $state(null);

	// Configure
	let teamName = $state('');
	let strategy = $state<'sequential' | 'parallel'>('sequential');
	let selectedProvider = $state('');
	let selectedModel = $state('');
	let customModelName = $state('');
	let customBaseUrl = $state('');
	let apiKey = $state('');
	let generating = $state(false);
	let generateError: string | null = $state(null);

	// Personas
	let personas = $state<PersonaEntry[]>([
		{ name: 'analyst', role: '', modelOverride: false, modelProvider: '', modelName: '', modelCustomName: '', modelBaseUrl: '', modelApiKey: '', agentId: null, agentName: null },
		{ name: 'reviewer', role: '', modelOverride: false, modelProvider: '', modelName: '', modelCustomName: '', modelBaseUrl: '', modelApiKey: '', agentId: null, agentName: null },
		{ name: 'advisor', role: '', modelOverride: false, modelProvider: '', modelName: '', modelCustomName: '', modelBaseUrl: '', modelApiKey: '', agentId: null, agentName: null },
	]);

	// Editor
	let yamlText = $state('');
	let issues = $state<ValidationIssue[]>([]);
	let isReady = $state(false);
	let saving = $state(false);
	let saveError: string | null = $state(null);
	let selectedDir = $state('');
	let filename = $state('role.yaml');

	// Validation debounce
	let validateTimer: ReturnType<typeof setTimeout> | undefined;

	// Success
	let savePath = $state('');
	let nextSteps = $state<string[]>([]);
	let teamId = $state('');
	let copied = $state(false);

	// -- Derived --------------------------------------------------------------

	const PERSONA_NAME_RE = /^[a-z0-9][a-z0-9-]*[a-z0-9]$/;

	const customPresetNames = $derived(
		new Set((options?.custom_presets ?? []).map((p) => p.name))
	);

	const personasValid = $derived(
		personas.length >= 2 &&
		personas.length <= 8 &&
		personas.every((p) => PERSONA_NAME_RE.test(p.name)) &&
		new Set(personas.map((p) => p.name)).size === personas.length
	);

	const canGenerate = $derived(
		teamName.trim().length > 0 &&
		selectedProvider.length > 0 &&
		personasValid
	);

	const strategies = [
		{
			value: 'sequential' as const,
			label: 'Sequential',
			description: 'Personas execute one after another, each building on the previous output.'
		},
		{
			value: 'parallel' as const,
			label: 'Parallel',
			description: 'Personas execute simultaneously, results are merged at the end.'
		}
	];

	// -- Actions --------------------------------------------------------------

	async function generate() {
		if (!options) return;
		generating = true;
		generateError = null;
		try {
			// Resolve API keys for persona model overrides that need them
			const resolvedPersonas: PersonaSeedEntry[] = [];
			for (const p of personas) {
				const entry: PersonaSeedEntry = { name: p.name, role: p.role, model: null };
				if (p.modelOverride) {
					const isCustom = customPresetNames.has(p.modelProvider);
					let resolvedApiKeyEnv: string | null = null;

					if (p.modelApiKey.trim() && isCustom) {
						const preset = options.custom_presets.find((pr) => pr.name === p.modelProvider);
						const keyResult = await saveProviderKey({
							preset: preset?.name !== 'custom' ? preset?.name : undefined,
							base_url: p.modelProvider === 'custom' ? p.modelBaseUrl : undefined,
							api_key: p.modelApiKey.trim()
						});
						resolvedApiKeyEnv = keyResult.env_var;
					} else if (isCustom) {
						const preset = options.custom_presets.find((pr) => pr.name === p.modelProvider);
						if (preset?.key_configured) {
							resolvedApiKeyEnv = preset.api_key_env;
						}
					}

					entry.model = {
						provider: p.modelProvider,
						name: isCustom ? p.modelCustomName : p.modelName,
						base_url: p.modelBaseUrl || null,
						api_key_env: resolvedApiKeyEnv
					};
				}
				resolvedPersonas.push(entry);
			}

			// Resolve team-level API key if needed
			const teamIsCustom = customPresetNames.has(selectedProvider);
			let teamApiKeyEnv: string | null = null;
			if (apiKey.trim() && teamIsCustom) {
				const preset = options.custom_presets.find((pr) => pr.name === selectedProvider);
				const keyResult = await saveProviderKey({
					preset: preset?.name !== 'custom' ? preset?.name : undefined,
					base_url: selectedProvider === 'custom' ? customBaseUrl : undefined,
					api_key: apiKey.trim()
				});
				teamApiKeyEnv = keyResult.env_var;
			} else if (teamIsCustom) {
				const preset = options.custom_presets.find((pr) => pr.name === selectedProvider);
				if (preset?.key_configured) {
					teamApiKeyEnv = preset.api_key_env;
				}
			}

			const result = await seedTeam({
				mode: 'blank',
				name: teamName.trim(),
				strategy,
				persona_count: personas.length,
				personas: resolvedPersonas,
				provider: selectedProvider || 'openai',
				model: (teamIsCustom ? customModelName.trim() : selectedModel) || null,
				base_url: customBaseUrl || null,
				api_key_env: teamApiKeyEnv
			});
			yamlText = result.yaml_text;
			issues = result.issues;
			isReady = result.ready;
			filename = `${teamName.trim().toLowerCase().replace(/[^a-z0-9]+/g, '-')}.yaml`;
			step = 'editor';
		} catch (err) {
			generateError = err instanceof ApiError ? err.detail : String(err);
		} finally {
			generating = false;
		}
	}

	function onYamlInput() {
		clearTimeout(validateTimer);
		validateTimer = setTimeout(async () => {
			try {
				const result = await validateTeam(yamlText);
				issues = result.issues;
				isReady = result.ready;
			} catch {
				// ignore
			}
		}, 500);
	}

	async function save() {
		if (!options) return;
		saving = true;
		saveError = null;
		try {
			const result = await saveTeam({
				yaml_text: yamlText,
				directory: selectedDir,
				filename
			});
			savePath = result.path;
			nextSteps = result.next_steps;
			teamId = result.team_id;
			step = 'success';
		} catch (err) {
			if (err instanceof ApiError && err.status === 409) {
				saveError = 'File already exists. Change the filename or choose a different directory.';
			} else {
				saveError = err instanceof ApiError ? err.detail : String(err);
			}
		} finally {
			saving = false;
		}
	}

	function createAnother() {
		step = 'configure';
		teamName = '';
		strategy = 'sequential';
		personas = [
			{ name: 'analyst', role: '', modelOverride: false, modelProvider: '', modelName: '', modelCustomName: '', modelBaseUrl: '', modelApiKey: '', agentId: null, agentName: null },
			{ name: 'reviewer', role: '', modelOverride: false, modelProvider: '', modelName: '', modelCustomName: '', modelBaseUrl: '', modelApiKey: '', agentId: null, agentName: null },
			{ name: 'advisor', role: '', modelOverride: false, modelProvider: '', modelName: '', modelCustomName: '', modelBaseUrl: '', modelApiKey: '', agentId: null, agentName: null },
		];
		yamlText = '';
		issues = [];
		isReady = false;
		generateError = null;
		saveError = null;
		filename = 'role.yaml';
		customModelName = '';
		customBaseUrl = '';
		apiKey = '';
	}

	async function copyPath() {
		await navigator.clipboard.writeText(savePath);
		copied = true;
		setTimeout(() => (copied = false), 2000);
	}

	// -- Init -----------------------------------------------------------------

	onMount(async () => {
		try {
			options = await fetchTeamBuilderOptions();
			if (options.detected_provider) selectedProvider = options.detected_provider;
			if (options.detected_model) selectedModel = options.detected_model;
			if (options.save_dirs.length > 0) selectedDir = options.save_dirs[0];
		} catch {
			optionsError = 'Could not load builder options.';
			toast.error('Failed to load builder options');
		} finally {
			optionsLoading = false;
		}
	});
</script>

<div class="space-y-5">
	<!-- Back link -->
	<a href="/teams" class="inline-flex items-center gap-1 text-[12px] text-fg-faint transition-[color] duration-150 hover:text-fg-muted">
		<ArrowLeft size={12} />
		Teams
	</a>

	<!-- Step indicator -->
	<div class="flex items-center gap-2 font-mono text-[12px] text-fg-faint">
		<span class:text-accent-primary={step === 'configure'} class:font-medium={step === 'configure'}>Configure</span>
		<span class="text-fg-faint/40">></span>
		<span class:text-accent-primary={step === 'editor'} class:font-medium={step === 'editor'}>Editor</span>
		<span class="text-fg-faint/40">></span>
		<span class:text-accent-primary={step === 'success'} class:font-medium={step === 'success'}>Saved</span>
	</div>

	{#if optionsLoading}
		<Skeleton class="h-64 bg-surface-1" />

	{:else if optionsError}
		<LoadError message={optionsError} onRetry={() => location.reload()} />

	{:else if step === 'configure'}
		<!-- STEP 1: CONFIGURE -->
		<div class="space-y-5">
			<h2 class="text-lg font-semibold text-fg">New Team</h2>

			<!-- Team name -->
			<div>
				<label for="team-name" class="mb-1 block text-[12px] font-medium text-fg-muted">Team name</label>
				<input
					id="team-name"
					bind:value={teamName}
					placeholder="my-review-team"
					class="w-full max-w-sm border border-edge bg-surface-1 px-3 py-2 font-mono text-[13px] text-fg outline-none transition-[border-color,box-shadow] duration-150 placeholder:text-fg-faint focus:border-accent-primary/40 focus:shadow-[0_0_0_3px_oklch(0.91_0.20_128/0.08)]"
				/>
			</div>

			<!-- Strategy selector -->
			<div>
				<span class="mb-2 block text-[12px] font-medium text-fg-muted">Strategy</span>
				<div class="grid grid-cols-1 gap-2 md:grid-cols-2">
					{#each strategies as s}
						<button
							class="border p-4 text-left transition-[border-color,background-color] duration-150 {strategy === s.value ? 'border-accent-primary/40 bg-accent-primary/[0.06]' : 'border-edge bg-surface-1 hover:border-accent-primary/20'}"
							onclick={() => (strategy = s.value)}
						>
							<div class="flex items-center justify-between">
								<span class="font-mono text-[13px] font-medium text-fg">{s.label}</span>
								{#if strategy === s.value}
									<Check size={14} class="text-accent-primary" />
								{/if}
							</div>
							<p class="mt-1 text-[12px] text-fg-faint">{s.description}</p>
						</button>
					{/each}
				</div>
			</div>

			<!-- Personas -->
			<div>
				<span class="mb-2 block text-[12px] font-medium text-fg-muted">
					Personas <span class="text-fg-faint">({personas.length})</span>
				</span>
				{#if options}
					<PersonaList
						bind:personas
						{strategy}
						providers={options.providers}
						customPresets={options.custom_presets}
						ollamaModels={options.ollama_models}
						ollamaBaseUrl={options.ollama_base_url}
						agents={options.agents}
					/>
				{/if}
			</div>

			<!-- Team-level model -->
			<div class="border-t border-edge pt-4">
				<span class="mb-2 block text-[12px] font-medium text-fg-muted">Team model</span>
				{#if options}
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
						compact={true}
					/>
				{/if}
			</div>

			<!-- Generate button -->
			<div class="flex items-center gap-3">
				<button
					class="flex items-center gap-1.5 rounded-full border border-accent-primary/30 bg-accent-primary/10 px-4 py-2 font-mono text-[13px] text-accent-primary transition-[background-color] duration-150 hover:bg-accent-primary/20 disabled:cursor-not-allowed disabled:opacity-40"
					onclick={generate}
					disabled={!canGenerate || generating}
				>
					{#if generating}
						<Loader2 size={14} class="animate-spin" />
						Generating...
					{:else}
						<Users size={14} />
						Generate
					{/if}
				</button>
				{#if generateError}
					<span class="text-[12px] text-status-fail">{generateError}</span>
				{/if}
			</div>
		</div>

	{:else if step === 'editor'}
		<!-- STEP 2: EDITOR -->
		<div class="space-y-4">
			<h2 class="text-lg font-semibold text-fg">team.yaml</h2>

			<!-- YAML editor -->
			<textarea
				class="h-80 w-full border border-edge bg-surface-1 p-3 font-mono text-[12px] text-fg outline-none transition-[border-color] duration-150 focus:border-accent-primary/40"
				bind:value={yamlText}
				oninput={onYamlInput}
				spellcheck="false"
			></textarea>

			<!-- Validation issues -->
			{#if issues.length > 0}
				<div class="space-y-1">
					{#each issues as issue}
						<div class="flex items-start gap-2 text-[12px]">
							{#if issue.severity === 'error'}
								<CircleX size={13} class="mt-0.5 shrink-0 text-status-fail" />
							{:else}
								<AlertTriangle size={13} class="mt-0.5 shrink-0 text-status-warn" />
							{/if}
							<span class="text-fg-faint"><span class="font-mono text-fg-muted">{issue.field}</span>: {issue.message}</span>
						</div>
					{/each}
				</div>
			{:else if isReady}
				<div class="flex items-center gap-1.5 text-[12px] text-status-ok">
					<CheckCircle size={13} />
					Valid
				</div>
			{/if}

			<!-- Save controls -->
			<div class="flex flex-wrap items-end gap-3 border-t border-edge pt-4">
				{#if options && options.save_dirs.length > 0}
					<div>
						<label for="save-dir" class="mb-1 block text-[12px] text-fg-faint">Directory</label>
						<select
							id="save-dir"
							bind:value={selectedDir}
							class="border border-edge bg-surface-1 px-2 py-1.5 font-mono text-[12px] text-fg outline-none"
						>
							{#each options.save_dirs as dir}
								<option value={dir}>{dir}</option>
							{/each}
						</select>
					</div>
				{/if}
				<div>
					<label for="filename" class="mb-1 block text-[12px] text-fg-faint">Filename</label>
					<input
						id="filename"
						bind:value={filename}
						class="w-48 border border-edge bg-surface-1 px-2 py-1.5 font-mono text-[12px] text-fg outline-none transition-[border-color] duration-150 focus:border-accent-primary/40"
					/>
				</div>
				<button
					class="flex items-center gap-1.5 rounded-full border border-accent-primary/30 bg-accent-primary/10 px-4 py-2 font-mono text-[13px] text-accent-primary transition-[background-color] duration-150 hover:bg-accent-primary/20 disabled:cursor-not-allowed disabled:opacity-40"
					onclick={save}
					disabled={saving || !isReady}
				>
					{#if saving}
						<Loader2 size={14} class="animate-spin" />
						Saving...
					{:else}
						Save Team
					{/if}
				</button>
				{#if saveError}
					<span class="text-[12px] text-status-fail">{saveError}</span>
				{/if}
			</div>

			<!-- Back to configure -->
			<button
				class="text-[12px] text-fg-faint transition-[color] duration-150 hover:text-fg-muted"
				onclick={() => (step = 'configure')}
			>
				Back to configure
			</button>
		</div>

	{:else if step === 'success'}
		<!-- STEP 3: SUCCESS -->
		<div class="mx-auto max-w-lg space-y-5 py-8 text-center">
			<div class="mx-auto flex h-12 w-12 items-center justify-center rounded-full border border-status-ok/30 bg-status-ok/10">
				<CheckCircle size={24} class="text-status-ok" />
			</div>
			<h2 class="text-lg font-semibold text-fg">Team saved</h2>

			<!-- Path -->
			<button
				class="mx-auto flex max-w-full items-center gap-2 overflow-hidden border border-edge bg-surface-1 px-3 py-1.5 font-mono text-[12px] text-fg-muted transition-[border-color] duration-150 hover:border-accent-primary/30"
				onclick={copyPath}
			>
				<span class="truncate">{savePath}</span>
				{#if copied}
					<Check size={12} class="shrink-0 text-status-ok" />
				{:else}
					<Copy size={12} class="shrink-0" />
				{/if}
			</button>

			<!-- CLI hint -->
			<div class="mx-auto max-w-sm text-left">
				<p class="mb-2 text-[12px] font-medium text-fg-muted">Run your team</p>
				<pre class="overflow-x-auto border border-edge bg-surface-1 px-3 py-1.5 font-mono text-[12px] text-fg-faint">initrunner run {savePath} -p "your task"</pre>
				{#if nextSteps.length > 0}
					<p class="mb-2 mt-4 text-[12px] font-medium text-fg-muted">Next steps</p>
					<div class="space-y-1">
						{#each nextSteps as ns}
							<pre class="overflow-x-auto border border-edge bg-surface-1 px-3 py-1.5 font-mono text-[12px] text-fg-faint">{ns}</pre>
						{/each}
					</div>
				{/if}
			</div>

			<!-- Actions -->
			<div class="flex items-center justify-center gap-3">
				<a
					href="/teams/{teamId}"
					class="rounded-full border border-accent-primary/30 bg-accent-primary/10 px-4 py-2 font-mono text-[12px] text-accent-primary transition-[background-color] duration-150 hover:bg-accent-primary/20"
				>
					View Team
				</a>
				<button
					class="rounded-full border border-edge bg-surface-1 px-4 py-2 font-mono text-[12px] text-fg-faint transition-[color,background-color] duration-150 hover:bg-surface-2 hover:text-fg-muted"
					onclick={createAnother}
				>
					Create Another
				</button>
			</div>
		</div>
	{/if}
</div>
