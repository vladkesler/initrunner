<script lang="ts">
	import { onMount } from 'svelte';
	import {
		fetchComposeBuilderOptions,
		seedCompose,
		validateCompose,
		saveCompose
	} from '$lib/api/compose';
	import { saveProviderKey } from '$lib/api/providers';
	import { ApiError } from '$lib/api/client';
	import { Skeleton } from '$lib/components/ui/skeleton';
	import AgentPicker from '$lib/components/ui/AgentPicker.svelte';
	import ModelSelector from '$lib/components/ui/ModelSelector.svelte';
	import type {
		ComposeBuilderOptions,
		PatternInfo,
		SlotAssignment,
		ValidationIssue
	} from '$lib/api/types';
	import {
		ArrowLeft,
		ArrowRight,
		Loader2,
		CircleX,
		TriangleAlert,
		CheckCircle,
		Minus,
		Plus,
		ChevronDown,
		Copy,
		Check
	} from 'lucide-svelte';

	// -- State ----------------------------------------------------------------

	type Step = 'configure' | 'editor' | 'success';

	let step: Step = $state('configure');
	let options = $state<ComposeBuilderOptions | null>(null);
	let optionsLoading = $state(true);

	// Configure
	let selectedPattern = $state<PatternInfo | null>(null);
	let serviceCount = $state(3);
	let slots = $state<{ name: string; agentId: string | null }[]>([]);
	let sharedMemory = $state(false);
	let selectedProvider = $state('');
	let selectedModel = $state('');
	let customModelName = $state('');
	let customBaseUrl = $state('');
	let apiKey = $state('');
	let projectName = $state('');
	let generating = $state(false);
	let generateError: string | null = $state(null);

	// Editor
	let composeYaml = $state('');
	let roleYamls = $state<Record<string, string>>({});
	let issues = $state<ValidationIssue[]>([]);
	let isReady = $state(false);
	let saving = $state(false);
	let saveError: string | null = $state(null);
	let selectedDir = $state('');
	let showRoles = $state(false);

	// Validation debounce
	let validateTimer: ReturnType<typeof setTimeout> | undefined;

	// Success
	let savePath = $state('');
	let nextSteps = $state<string[]>([]);
	let composeId = $state('');
	let copied = $state(false);

	// -- Derived --------------------------------------------------------------

	const canGenerate = $derived(selectedPattern !== null && projectName.trim().length > 0);

	const customPresetNames = $derived(
		new Set((options?.custom_presets ?? []).map((p) => p.name))
	);
	const isCustomEndpoint = $derived(customPresetNames.has(selectedProvider));
	const activePreset = $derived(
		(options?.custom_presets ?? []).find((p) => p.name === selectedProvider) ?? null
	);

	// -- Slot management ------------------------------------------------------

	function updateSlots() {
		if (!selectedPattern) return;
		let names: string[];
		if (selectedPattern.fixed_topology) {
			names = [...selectedPattern.slot_names];
		} else if (selectedPattern.name === 'pipeline') {
			names = Array.from({ length: serviceCount }, (_, i) => `step-${i + 1}`);
		} else {
			// fan-out
			const workers = serviceCount - 1;
			names = ['dispatcher', ...Array.from({ length: workers }, (_, i) => `worker-${i + 1}`)];
		}
		// Preserve existing assignments
		const existing = new Map(slots.map((s) => [s.name, s.agentId]));
		slots = names.map((n) => ({ name: n, agentId: existing.get(n) ?? null }));
	}

	function selectPattern(p: PatternInfo) {
		selectedPattern = p;
		serviceCount = p.fixed_topology ? p.min_services : 3;
		updateSlots();
	}

	function adjustCount(delta: number) {
		if (!selectedPattern || selectedPattern.fixed_topology) return;
		const next = serviceCount + delta;
		if (next < selectedPattern.min_services) return;
		if (selectedPattern.max_services && next > selectedPattern.max_services) return;
		serviceCount = next;
		updateSlots();
	}

	// -- Actions --------------------------------------------------------------

	async function generate() {
		if (!options || !selectedPattern) return;
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
			} else if (isCustomEndpoint && activePreset?.key_configured) {
				resolvedApiKeyEnv = activePreset.api_key_env;
			}

			const services: SlotAssignment[] = slots.map((s) => ({
				slot: s.name,
				agent_id: s.agentId
			}));
			const result = await seedCompose({
				pattern: selectedPattern.name,
				name: projectName.trim(),
				services,
				service_count: serviceCount,
				shared_memory: sharedMemory,
				provider: selectedProvider || 'openai',
				model: (isCustomEndpoint ? customModelName.trim() : selectedModel) || null,
				base_url: customBaseUrl || null,
				api_key_env: resolvedApiKeyEnv
			});
			composeYaml = result.compose_yaml;
			roleYamls = result.role_yamls;
			issues = result.issues;
			isReady = result.ready;
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
				const result = await validateCompose(composeYaml);
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
			const result = await saveCompose({
				compose_yaml: composeYaml,
				role_yamls: roleYamls,
				directory: selectedDir,
				project_name: projectName.trim()
			});
			savePath = result.path;
			nextSteps = result.next_steps;
			composeId = result.compose_id;
			step = 'success';
		} catch (err) {
			if (err instanceof ApiError && err.status === 409) {
				saveError = 'Directory already exists. Change the project name or enable force overwrite.';
			} else {
				saveError = err instanceof ApiError ? err.detail : String(err);
			}
		} finally {
			saving = false;
		}
	}

	function createAnother() {
		step = 'configure';
		selectedPattern = null;
		serviceCount = 3;
		slots = [];
		sharedMemory = false;
		customModelName = '';
		customBaseUrl = '';
		apiKey = '';
		projectName = '';
		composeYaml = '';
		roleYamls = {};
		issues = [];
		isReady = false;
		generateError = null;
		saveError = null;
	}

	async function copyPath() {
		await navigator.clipboard.writeText(savePath);
		copied = true;
		setTimeout(() => (copied = false), 2000);
	}

	// -- Init -----------------------------------------------------------------

	onMount(async () => {
		try {
			options = await fetchComposeBuilderOptions();
			if (options.detected_provider) selectedProvider = options.detected_provider;
			if (options.detected_model) selectedModel = options.detected_model;
			if (options.save_dirs.length > 0) selectedDir = options.save_dirs[0];
		} catch {
			// API not available
		} finally {
			optionsLoading = false;
		}
	});
</script>

<div class="space-y-5">
	<!-- Back link -->
	<a href="/compose" class="inline-flex items-center gap-1 text-[12px] text-fg-faint transition-[color] duration-150 hover:text-fg-muted">
		<ArrowLeft size={12} />
		Compose
	</a>

	<!-- Step indicator -->
	<div class="flex items-center gap-2 text-[12px] font-mono text-fg-faint">
		<span class:text-accent-primary={step === 'configure'} class:font-medium={step === 'configure'}>Configure</span>
		<span class="text-fg-faint/40">></span>
		<span class:text-accent-primary={step === 'editor'} class:font-medium={step === 'editor'}>Editor</span>
		<span class="text-fg-faint/40">></span>
		<span class:text-accent-primary={step === 'success'} class:font-medium={step === 'success'}>Saved</span>
	</div>

	{#if optionsLoading}
		<Skeleton class="h-64 bg-surface-1" />

	{:else if step === 'configure'}
		<!-- STEP 1: CONFIGURE -->
		<div class="space-y-5">
			<h2 class="text-lg font-semibold text-fg">New Composition</h2>

			<!-- Project name -->
			<div>
				<label for="project-name" class="mb-1 block text-[12px] font-medium text-fg-muted">Project name</label>
				<input
					id="project-name"
					bind:value={projectName}
					placeholder="my-pipeline"
					class="w-full max-w-sm border border-edge bg-surface-1 px-3 py-2 font-mono text-[13px] text-fg outline-none transition-[border-color,box-shadow] duration-150 placeholder:text-fg-faint focus:border-accent-primary/40 focus:shadow-[0_0_0_3px_oklch(0.91_0.20_128/0.08)]"
				/>
			</div>

			<!-- Pattern picker -->
			<div>
				<span class="mb-2 block text-[12px] font-medium text-fg-muted">Pattern</span>
				<div class="grid grid-cols-1 gap-2 md:grid-cols-3">
					{#if options}
						{#each options.patterns as pattern}
							<button
								class="border p-4 text-left transition-[border-color,background-color] duration-150 {selectedPattern?.name === pattern.name ? 'border-accent-primary/40 bg-accent-primary/[0.06]' : 'border-edge bg-surface-1 hover:border-accent-primary/20'}"
								onclick={() => selectPattern(pattern)}
							>
								<div class="flex items-center justify-between">
									<span class="font-mono text-[13px] font-medium text-fg">{pattern.name}</span>
									{#if pattern.fixed_topology}
										<span class="rounded-full border border-edge bg-surface-2 px-1.5 py-0.5 font-mono text-[10px] text-fg-faint">fixed</span>
									{/if}
								</div>
								<p class="mt-1 text-[12px] text-fg-faint">{pattern.description}</p>
								<p class="mt-1 font-mono text-[11px] text-fg-faint/60">
									{#if pattern.fixed_topology}
										{pattern.slot_names.length} services
									{:else}
										{pattern.min_services}+ services
									{/if}
								</p>
							</button>
						{/each}
					{/if}
				</div>
			</div>

			<!-- Slot picker -->
			{#if selectedPattern}
				<div>
					<div class="mb-2 flex items-center justify-between">
						<span class="text-[12px] font-medium text-fg-muted">Services</span>
						{#if !selectedPattern.fixed_topology}
							<div class="flex items-center gap-1.5">
								<button
									class="rounded-full border border-edge bg-surface-1 p-1 text-fg-faint transition-[color,background-color] duration-150 hover:bg-surface-2 hover:text-fg-muted disabled:opacity-30"
									onclick={() => adjustCount(-1)}
									disabled={serviceCount <= selectedPattern.min_services}
								>
									<Minus size={12} />
								</button>
								<span class="font-mono text-[12px] text-fg-muted">{serviceCount}</span>
								<button
									class="rounded-full border border-edge bg-surface-1 p-1 text-fg-faint transition-[color,background-color] duration-150 hover:bg-surface-2 hover:text-fg-muted disabled:opacity-30"
									onclick={() => adjustCount(1)}
									disabled={selectedPattern.max_services !== null && serviceCount >= selectedPattern.max_services}
								>
									<Plus size={12} />
								</button>
							</div>
						{/if}
					</div>

					<!-- Slot flow diagram -->
					<div class="space-y-1.5">
						{#each slots as slot, idx}
							<div class="flex items-center gap-2">
								{#if idx > 0}
									<div class="ml-4 -mt-1.5 -mb-0.5 h-3 w-px bg-fg-faint/20"></div>
								{/if}
							</div>
							<div class="flex items-center gap-2">
								<span class="w-24 shrink-0 text-right font-mono text-[12px] text-fg-faint">{slot.name}</span>
								<ArrowRight size={12} class="shrink-0 text-fg-faint/40" />
								{#if options}
									<div class="flex-1">
										<AgentPicker
											agents={options.agents}
											selected={slot.agentId}
											onSelect={(agent) => { slots[idx].agentId = agent?.id ?? null; }}
											placeholder="Generate placeholder"
										/>
									</div>
								{/if}
							</div>
						{/each}
					</div>
				</div>

				<!-- Options -->
				<div class="flex flex-wrap items-center gap-4 border-t border-edge pt-4">
					<label class="flex items-center gap-2 text-[12px] text-fg-muted">
						<input type="checkbox" bind:checked={sharedMemory} class="accent-accent-primary" />
						Shared memory
					</label>
				</div>

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

				<!-- Generate button -->
				<div class="flex items-center gap-3">
					<button
						class="flex items-center gap-1.5 rounded-full border border-accent-primary/30 bg-accent-primary/10 px-4 py-2 font-mono text-[13px] text-accent-primary transition-[background-color] duration-150 hover:bg-accent-primary/20 disabled:opacity-40 disabled:cursor-not-allowed"
						onclick={generate}
						disabled={!canGenerate || generating}
					>
						{#if generating}
							<Loader2 size={14} class="animate-spin" />
							Generating...
						{:else}
							Generate
						{/if}
					</button>
					{#if generateError}
						<span class="text-[12px] text-status-fail">{generateError}</span>
					{/if}
				</div>
			{/if}
		</div>

	{:else if step === 'editor'}
		<!-- STEP 2: EDITOR -->
		<div class="space-y-4">
			<h2 class="text-lg font-semibold text-fg">compose.yaml</h2>

			<!-- YAML editor -->
			<textarea
				class="h-80 w-full border border-edge bg-surface-1 p-3 font-mono text-[12px] text-fg outline-none transition-[border-color] duration-150 focus:border-accent-primary/40"
				bind:value={composeYaml}
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
								<TriangleAlert size={13} class="mt-0.5 shrink-0 text-status-warn" />
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

			<!-- Generated roles (collapsible) -->
			{#if Object.keys(roleYamls).length > 0}
				<button
					class="flex items-center gap-1.5 text-[12px] text-fg-faint transition-[color] duration-150 hover:text-fg-muted"
					onclick={() => (showRoles = !showRoles)}
				>
					<ChevronDown size={12} class="transition-transform duration-150 {showRoles ? 'rotate-0' : '-rotate-90'}" />
					Generated roles ({Object.keys(roleYamls).length})
				</button>
				{#if showRoles}
					<div class="space-y-2 border-l-2 border-edge pl-3">
						{#each Object.entries(roleYamls) as [filename, yaml]}
							<div>
								<p class="mb-1 font-mono text-[11px] text-fg-muted">roles/{filename}</p>
								<pre class="max-h-40 overflow-auto border border-edge bg-surface-2 p-2 font-mono text-[11px] text-fg-faint">{yaml}</pre>
							</div>
						{/each}
					</div>
				{/if}
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
				<button
					class="flex items-center gap-1.5 rounded-full border border-accent-primary/30 bg-accent-primary/10 px-4 py-2 font-mono text-[13px] text-accent-primary transition-[background-color] duration-150 hover:bg-accent-primary/20 disabled:opacity-40 disabled:cursor-not-allowed"
					onclick={save}
					disabled={saving || !isReady}
				>
					{#if saving}
						<Loader2 size={14} class="animate-spin" />
						Saving...
					{:else}
						Save
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
			<h2 class="text-lg font-semibold text-fg">Composition saved</h2>

			<!-- Path -->
			<button
				class="mx-auto flex items-center gap-2 border border-edge bg-surface-1 px-3 py-1.5 font-mono text-[12px] text-fg-muted transition-[border-color] duration-150 hover:border-accent-primary/30"
				onclick={copyPath}
			>
				{savePath}
				{#if copied}
					<Check size={12} class="text-status-ok" />
				{:else}
					<Copy size={12} />
				{/if}
			</button>

			<!-- Next steps -->
			<div class="mx-auto max-w-sm text-left">
				<p class="mb-2 text-[12px] font-medium text-fg-muted">Next steps</p>
				<div class="space-y-1">
					{#each nextSteps as ns}
						<pre class="border border-edge bg-surface-1 px-3 py-1.5 font-mono text-[12px] text-fg-faint">{ns}</pre>
					{/each}
				</div>
			</div>

			<!-- Actions -->
			<div class="flex items-center justify-center gap-3">
				<a
					href="/compose/{composeId}"
					class="rounded-full border border-accent-primary/30 bg-accent-primary/10 px-4 py-2 font-mono text-[12px] text-accent-primary transition-[background-color] duration-150 hover:bg-accent-primary/20"
				>
					View Composition
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
