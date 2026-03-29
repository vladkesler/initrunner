<script lang="ts">
	import { onMount } from 'svelte';
	import { request } from '$lib/api/client';
	import { runDoctor, listToolTypes, getDefaultModel, saveDefaultModel, resetDefaultModel, type DefaultModelResponse } from '$lib/api/system';
	import { getBuilderOptions, type BuilderOptions } from '$lib/api/builder';
	import { getProviderStatus, type ProviderStatusResponse } from '$lib/api/providers';
	import type { HealthStatus, DoctorCheck, ToolType } from '$lib/api/types';
	import { Skeleton } from '$lib/components/ui/skeleton';
	import { Stethoscope, RefreshCw, CheckCircle, AlertTriangle, XCircle, Wrench, Save, RotateCcw, Info } from 'lucide-svelte';
	import ProviderStatusBanner from '$lib/components/ui/ProviderStatusBanner.svelte';
	import ModelSelector from '$lib/components/ui/ModelSelector.svelte';
	import { toast } from '$lib/stores/toast.svelte';

	let version = $state('');
	let providerData = $state<ProviderStatusResponse | null>(null);
	let doctorChecks = $state<DoctorCheck[]>([]);
	let embeddingChecks = $state<DoctorCheck[]>([]);
	let tools = $state<ToolType[]>([]);
	let loading = $state(true);
	let doctorLoading = $state(false);
	let toolsLoading = $state(true);

	// Default model state
	let defaultModel = $state<DefaultModelResponse | null>(null);
	let builderOpts = $state<BuilderOptions | null>(null);
	let dmProvider = $state('');
	let dmModel = $state('');
	let dmCustomModel = $state('');
	let dmCustomUrl = $state('');
	let dmApiKey = $state('');
	let dmSaving = $state(false);

	const dmDirty = $derived(
		defaultModel !== null &&
			(dmProvider !== (defaultModel.provider || '') ||
				(dmModel || dmCustomModel) !== (defaultModel.model || ''))
	);

	function initModelSelector(dm: DefaultModelResponse) {
		dmProvider = dm.provider || '';
		dmModel = dm.model || '';
		dmCustomModel = '';
		dmCustomUrl = dm.base_url || '';
	}

	async function handleSaveDefault() {
		dmSaving = true;
		try {
			const result = await saveDefaultModel({
				provider: dmProvider,
				model: dmModel || dmCustomModel,
				base_url: dmCustomUrl || null,
				api_key_env: null
			});
			defaultModel = result;
			initModelSelector(result);
			toast.success('Default model saved');
		} catch {
			toast.error('Failed to save default model');
		} finally {
			dmSaving = false;
		}
	}

	async function handleResetDefault() {
		dmSaving = true;
		try {
			const result = await resetDefaultModel();
			defaultModel = result;
			initModelSelector(result);
			toast.success('Default model reset to auto-detect');
		} catch {
			toast.error('Failed to reset default model');
		} finally {
			dmSaving = false;
		}
	}

	function statusIcon(status: string) {
		if (status === 'ok') return CheckCircle;
		if (status === 'warn') return AlertTriangle;
		return XCircle;
	}

	function statusColor(status: string): string {
		if (status === 'ok') return 'text-ok';
		if (status === 'warn') return 'text-warn';
		return 'text-fail';
	}

	async function loadDoctor() {
		doctorLoading = true;
		try {
			const res = await runDoctor();
			doctorChecks = res.checks;
			embeddingChecks = res.embedding_checks;
		} catch {
			toast.error('Failed to run health check');
		} finally {
			doctorLoading = false;
		}
	}

	async function reloadProviders() {
		try {
			providerData = await getProviderStatus();
			// Refresh doctor if already loaded
			if (doctorChecks.length > 0) {
				loadDoctor();
			}
		} catch {
			toast.error('Failed to reload providers');
		}
	}

	onMount(async () => {
		try {
			const [health, pd, t, dm, bo] = await Promise.all([
				request<HealthStatus>('/api/health'),
				getProviderStatus(),
				listToolTypes(),
				getDefaultModel(),
				getBuilderOptions()
			]);
			version = health.version;
			providerData = pd;
			tools = t;
			defaultModel = dm;
			builderOpts = bo;
			initModelSelector(dm);
		} catch {
			toast.error('Failed to load system status');
		} finally {
			loading = false;
			toolsLoading = false;
		}
	});
</script>

<div class="space-y-8">
	<!-- Header -->
	<div class="flex items-center gap-3">
		<h1 class="text-xl font-semibold tracking-[-0.02em] text-fg">System</h1>
		{#if version}
			<span class="border border-edge bg-surface-1 px-2 py-0.5 font-mono text-[12px] text-fg-faint">v{version}</span>
		{/if}
	</div>

	{#if loading}
		<Skeleton class="h-40 bg-surface-1" />
	{:else}
		<!-- Providers -->
		<div>
			<h2 class="mb-1 font-mono text-[12px] font-medium uppercase tracking-[0.1em] text-fg-faint">Providers</h2>
			<p class="mb-3 text-[12px] text-fg-faint">API keys that enable access to LLM services. Add keys here to unlock providers.</p>
			{#if providerData}
				<ProviderStatusBanner
					providerStatus={providerData.providers}
					detectedProvider={providerData.detected_provider}
					mode="full"
					onConfigured={reloadProviders}
				/>
			{/if}
		</div>

		<!-- Default Model -->
		<div>
			<h2 class="mb-1 font-mono text-[12px] font-medium uppercase tracking-[0.1em] text-fg-faint">Default Model</h2>
			<p class="mb-3 text-[12px] text-fg-faint">Which specific model agents use when their YAML doesn't pin one. Agents with an explicit <code class="font-mono">model:</code> section ignore this.</p>

			{#if defaultModel && builderOpts}
				{#if defaultModel.source === 'initrunner_model_env'}
					<div class="mb-3 flex items-start gap-2 border border-edge bg-surface-1 px-3 py-2 text-[13px] text-fg-faint">
						<Info size={13} class="mt-0.5 shrink-0 text-fg-faint" />
						<span>Currently overridden by <code class="font-mono text-fg-muted">INITRUNNER_MODEL</code> env var. The setting below will take effect when the env var is removed.</span>
					</div>
				{:else if defaultModel.source === 'auto_detected'}
					<div class="mb-3 flex items-start gap-2 border border-edge bg-surface-1 px-3 py-2 text-[13px] text-fg-faint">
						<Info size={13} class="mt-0.5 shrink-0 text-fg-faint" />
						<span>Auto-detected from your API keys. Save below to pin a specific model.</span>
					</div>
				{:else if defaultModel.source === 'none'}
					<div class="mb-3 flex items-start gap-2 border border-warn/20 bg-warn/5 px-3 py-2 text-[13px] text-fg-faint">
						<Info size={13} class="mt-0.5 shrink-0 text-warn" />
						<span>No provider configured. Add an API key above, then select a model here.</span>
					</div>
				{/if}

				<div class="border border-edge bg-surface-1 p-4">
					<ModelSelector
						providers={builderOpts.providers}
						customPresets={builderOpts.custom_presets}
						ollamaModels={builderOpts.ollama_models}
						ollamaBaseUrl={builderOpts.ollama_base_url}
						bind:selectedProvider={dmProvider}
						bind:selectedModel={dmModel}
						bind:customModelName={dmCustomModel}
						bind:customBaseUrl={dmCustomUrl}
						bind:apiKey={dmApiKey}
						compact
					/>

					<div class="mt-4 flex items-center gap-3">
						<button
							class="flex items-center gap-1.5 rounded-full border border-edge px-4 py-1.5 text-[13px] text-fg-muted transition-[color,background-color,border-color] duration-150 hover:bg-surface-2 hover:text-fg hover:border-accent-primary/20 disabled:opacity-40"
							onclick={handleSaveDefault}
							disabled={dmSaving || !dmDirty}
						>
							<Save size={12} />
							{dmSaving ? 'Saving...' : 'Save Default'}
						</button>

						{#if defaultModel.source === 'run_yaml'}
							<button
								class="flex items-center gap-1.5 rounded-full border border-edge px-3 py-1.5 text-[13px] text-fg-faint transition-[color,background-color,border-color] duration-150 hover:bg-surface-2 hover:text-fg-muted hover:border-edge"
								onclick={handleResetDefault}
								disabled={dmSaving}
							>
								<RotateCcw size={11} />
								Reset to auto-detect
							</button>
							<span class="text-[12px] text-fg-faint">
								Saved in <code class="font-mono">run.yaml</code>
							</span>
						{/if}
					</div>
				</div>
			{:else}
				<Skeleton class="h-32 bg-surface-1" />
			{/if}
		</div>

		<!-- Doctor -->
		<div>
			<div class="mb-3 flex items-center gap-3">
				<h2 class="font-mono text-[12px] font-medium uppercase tracking-[0.1em] text-fg-faint">Health Check</h2>
				<button
					class="flex items-center gap-1.5 rounded-full border border-edge px-3 py-1 text-[13px] text-fg-faint transition-[color,background-color,border-color] duration-150 hover:bg-surface-2 hover:text-fg-muted hover:border-accent-primary/20"
					class:opacity-50={doctorLoading}
					onclick={loadDoctor}
					disabled={doctorLoading}
				>
					{#if doctorLoading}
						<RefreshCw size={11} class="animate-spin" />
						Checking...
					{:else}
						<Stethoscope size={11} />
						Run Doctor
					{/if}
				</button>
			</div>

			{#if doctorChecks.length === 0 && !doctorLoading}
				<div class="border border-edge bg-surface-1 px-4 py-8 text-center text-[13px] text-fg-faint">
					Click "Run Doctor" to check provider connectivity and SDK availability.
				</div>
			{:else if doctorChecks.length > 0}
				<div class="space-y-1">
					{#each doctorChecks as check}
						{@const Icon = statusIcon(check.status)}
						<div class="card-surface flex items-center gap-3 bg-surface-1 px-4 py-2.5">
							<Icon size={14} class={statusColor(check.status)} />
							<span class="font-mono text-[13px] text-fg-muted">{check.name}</span>
							<span class="ml-auto text-[13px] {statusColor(check.status)}">{check.message}</span>
						</div>
					{/each}
				</div>
			{/if}
		</div>

		<!-- Embedding Providers -->
		{#if embeddingChecks.length > 0}
			<div>
				<h2 class="mb-3 font-mono text-[12px] font-medium uppercase tracking-[0.1em] text-fg-faint">Embedding Providers</h2>
				<div class="space-y-1">
					{#each embeddingChecks as check}
						{@const Icon = statusIcon(check.status)}
						<div class="card-surface flex items-center gap-3 bg-surface-1 px-4 py-2.5">
							<Icon size={14} class={statusColor(check.status)} />
							<span class="font-mono text-[13px] text-fg-muted">{check.name}</span>
							<span class="ml-auto text-[13px] {statusColor(check.status)}">{check.message}</span>
						</div>
					{/each}
				</div>
				<p class="mt-2 text-[12px] text-fg-faint">Anthropic uses OpenAI embeddings (OPENAI_API_KEY) for RAG/memory.</p>
			</div>
		{/if}

		<!-- Tool Registry -->
		<div>
			<h2 class="mb-3 flex items-center gap-2 font-mono text-[12px] font-medium uppercase tracking-[0.1em] text-fg-faint">
				<Wrench size={12} />
				Tool Registry
				{#if tools.length > 0}
					<span class="rounded-full border border-edge bg-surface-2 px-2 py-0.5 text-[11px]">{tools.length}</span>
				{/if}
			</h2>

			{#if toolsLoading}
				<Skeleton class="h-32 bg-surface-1" />
			{:else if tools.length === 0}
				<div class="border border-edge bg-surface-1 px-4 py-8 text-center text-[13px] text-fg-faint">
					No tool types registered.
				</div>
			{:else}
				<div class="overflow-hidden border border-edge">
					<div class="grid grid-cols-1 divide-y divide-edge-subtle md:grid-cols-2 md:divide-y-0">
						{#each tools as tool, i}
							<div
								class="px-4 py-2.5"
								class:border-r={i % 2 === 0}
								class:border-edge-subtle={i % 2 === 0}
								class:border-b={i < tools.length - (tools.length % 2 === 0 ? 2 : 1)}
								class:border-b-edge-subtle={i < tools.length - (tools.length % 2 === 0 ? 2 : 1)}
							>
								<div class="font-mono text-[13px] text-fg-muted">{tool.name}</div>
								<div class="mt-0.5 text-[13px] text-fg-faint">{tool.description}</div>
							</div>
						{/each}
					</div>
				</div>
			{/if}
		</div>
	{/if}
</div>
