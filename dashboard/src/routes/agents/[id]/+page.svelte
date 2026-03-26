<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { onMount } from 'svelte';
	import { getAgentDetail, getAgentYaml, deleteAgent, getAgentTriggerStats } from '$lib/api/agents';
	import { fetchAuditStats } from '$lib/api/system';
	import type { AgentDetail, AuditStats, TriggerStat } from '$lib/api/types';
	import { loadOr404 } from '$lib/utils/load';
	import { toast } from '$lib/stores/toast.svelte';
	import { Skeleton } from '$lib/components/ui/skeleton';
	import { Tabs, TabsContent, TabsList, TabsTrigger } from '$lib/components/ui/tabs';
	import ConfirmDeleteDialog from '$lib/components/ui/ConfirmDeleteDialog.svelte';
	import LoadError from '$lib/components/ui/LoadError.svelte';
	import ConfigPanel from '$lib/components/agents/ConfigPanel.svelte';
	import TriggerPanel from '$lib/components/agents/TriggerPanel.svelte';
	import RunPanel from '$lib/components/runs/RunPanel.svelte';
	import HistoryTab from '$lib/components/agents/HistoryTab.svelte';
	import MemoryTab from '$lib/components/agents/MemoryTab.svelte';
	import IngestTab from '$lib/components/agents/IngestTab.svelte';
	import EditorTab from '$lib/components/agents/EditorTab.svelte';
	import {
		AlertTriangle,
		ArrowLeft,
		Activity,
		CheckCircle,
		Coins,
		Timer,
		Play,
		History,
		Brain,
		Database,
		Settings,
		FileCode,
		Trash2
	} from 'lucide-svelte';

	let detail: AgentDetail | null = $state(null);
	let yaml = $state('');
	let agentPath = $state('');
	let stats: AuditStats | null = $state(null);
	let triggerStats: TriggerStat[] = $state([]);
	let loading = $state(true);
	let loadError = $state(false);
	let statsLoading = $state(true);
	let runVersion = $state(0);
	let deleteDialogOpen = $state(false);

	const agentId = $derived(page.params.id ?? '');

	// Persist active tab per agent
	const tabKey = $derived(`agent-tab-${agentId}`);
	let activeTab = $state('run');

	// Status dot color based on error + success rate
	const statusColor = $derived.by(() => {
		if (detail?.error) return 'bg-fail';
		if (!stats) return 'bg-fg-faint';
		if (stats.success_rate >= 80) return 'bg-ok';
		if (stats.success_rate >= 50) return 'bg-warn';
		return 'bg-fail';
	});

	const statusGlow = $derived.by(() => {
		if (detail?.error) return 'var(--color-fail)';
		if (!stats) return 'transparent';
		if (stats.success_rate >= 80) return 'var(--color-ok)';
		if (stats.success_rate >= 50) return 'var(--color-warn)';
		return 'var(--color-fail)';
	});

	function onTabChange(value: string) {
		activeTab = value;
		try {
			localStorage.setItem(tabKey, value);
		} catch {
			// localStorage unavailable
		}
	}

	async function reload() {
		const [d, y] = await Promise.all([getAgentDetail(agentId), getAgentYaml(agentId)]);
		detail = d;
		yaml = y.yaml;
		agentPath = y.path;
	}

	async function refreshStats() {
		if (!detail) return;
		try {
			stats = await fetchAuditStats({ agent_name: detail.name });
		} catch {
			// stats are best-effort
		}
		if (detail.triggers.length > 0) {
			try {
				triggerStats = await getAgentTriggerStats(agentId);
			} catch {
				// trigger stats are best-effort
			}
		}
	}

	onMount(async () => {
		// Restore saved tab
		try {
			const saved = localStorage.getItem(tabKey);
			if (saved && ['run', 'history', 'memory', 'ingest', 'config', 'editor'].includes(saved)) {
				activeTab = saved;
			}
		} catch {
			// ignore
		}

		// Stage 1: detail + yaml (parallel)
		const result = await loadOr404(() => reload(), 'Failed to load agent');
		if (!result.ok && !result.notFound) loadError = true;
		loading = false;

		// Stage 2: stats + trigger stats (needs detail.name)
		if (detail) {
			await refreshStats();
		}
		statsLoading = false;
	});
</script>

<div class="flex h-full flex-col gap-5">
	<!-- Back link -->
	<a
		href="/agents"
		class="inline-flex items-center gap-1.5 text-[13px] text-fg-faint transition-[color] duration-150 hover:text-fg-muted"
	>
		<ArrowLeft size={14} />
		Agents
	</a>

	{#if loading}
		<Skeleton class="h-6 w-48 bg-surface-1" />
		<Skeleton class="h-10 bg-surface-1" />
		<Skeleton class="h-64 bg-surface-1" />
	{:else if loadError}
		<LoadError message="Failed to load agent" onRetry={() => location.reload()} />
	{:else if detail}
		<!-- Header -->
		<div>
			<div class="flex items-center gap-3">
				<h1 class="text-xl font-semibold tracking-[-0.02em] text-fg" style="text-wrap: balance">
					{detail.name}
				</h1>
				{#if detail.model.provider}
					<span
						class="border border-edge bg-surface-1 px-2 py-0.5 font-mono text-[12px] text-fg-faint"
					>
						{detail.model.provider}/{detail.model.name}
					</span>
				{/if}
				<span
					class="inline-block h-2 w-2 rounded-full {statusColor}"
					style="box-shadow: 0 0 6px {statusGlow}"
				></span>
				<button
					class="ml-auto flex items-center gap-1 rounded-[min(var(--radius-md),12px)] border border-transparent bg-destructive/10 px-2.5 py-1 text-[0.8rem] font-medium text-destructive transition-all hover:bg-destructive/20"
					onclick={() => (deleteDialogOpen = true)}
				>
					<Trash2 size={13} />
					Delete
				</button>
			</div>
			{#if detail.description}
				<p class="mt-1 text-[13px] text-fg-muted">{detail.description}</p>
			{/if}
		</div>

		<!-- Error block -->
		{#if detail.error}
			<div class="border-l-2 border-l-fail bg-fail/5 px-3 py-2">
				<p class="font-mono text-sm text-fail">{detail.error}</p>
			</div>
		{/if}

		<!-- Provider warning -->
		{#if detail.provider_warning}
			<div class="flex items-start gap-2.5 border border-warn/30 bg-warn/5 px-4 py-3">
				<AlertTriangle size={14} class="mt-0.5 shrink-0 text-warn" />
				<span class="font-mono text-[13px] text-fg-muted">{detail.provider_warning}</span>
			</div>
		{/if}

		<!-- Stats bar -->
		{#if statsLoading}
			<div class="grid grid-cols-2 gap-2 lg:grid-cols-4">
				{#each Array(4) as _}
					<Skeleton class="h-[60px] bg-surface-1" />
				{/each}
			</div>
		{:else if stats}
			<div class="grid grid-cols-2 gap-2 lg:grid-cols-4">
				<div
					class="card-surface flex items-center gap-2.5 bg-surface-1 px-3 py-2 animate-fade-in-up"
					style="animation-delay: 0ms"
				>
					<Activity size={14} class="shrink-0 text-accent-primary/60" />
					<div>
						<div
							class="font-mono text-[18px] font-semibold tracking-[-0.02em] text-fg"
							style="font-variant-numeric: tabular-nums"
						>
							{stats.total_runs.toLocaleString()}
						</div>
						<div class="text-[12px] text-fg-faint">runs</div>
					</div>
				</div>
				<div
					class="card-surface flex items-center gap-2.5 bg-surface-1 px-3 py-2 animate-fade-in-up"
					style="animation-delay: 60ms"
				>
					<CheckCircle
						size={14}
						class="shrink-0 {stats.success_rate >= 90
							? 'text-ok'
							: stats.success_rate >= 70
								? 'text-warn'
								: 'text-fail'}"
					/>
					<div>
						<div
							class="font-mono text-[18px] font-semibold tracking-[-0.02em] text-fg"
							style="font-variant-numeric: tabular-nums"
						>
							{stats.success_rate}%
						</div>
						<div class="text-[12px] text-fg-faint">success</div>
					</div>
				</div>
				<div
					class="card-surface flex items-center gap-2.5 bg-surface-1 px-3 py-2 animate-fade-in-up"
					style="animation-delay: 120ms"
				>
					<Coins size={14} class="shrink-0 text-accent-primary/60" />
					<div>
						<div
							class="font-mono text-[18px] font-semibold tracking-[-0.02em] text-fg"
							style="font-variant-numeric: tabular-nums"
						>
							{stats.total_tokens.toLocaleString()}
						</div>
						<div class="text-[12px] text-fg-faint">tokens</div>
					</div>
				</div>
				<div
					class="card-surface flex items-center gap-2.5 bg-surface-1 px-3 py-2 animate-fade-in-up"
					style="animation-delay: 180ms"
				>
					<Timer size={14} class="shrink-0 text-accent-primary/60" />
					<div>
						<div
							class="font-mono text-[18px] font-semibold tracking-[-0.02em] text-fg"
							style="font-variant-numeric: tabular-nums"
						>
							{stats.avg_duration_ms.toLocaleString()}ms
						</div>
						<div class="text-[12px] text-fg-faint">avg duration</div>
					</div>
				</div>
			</div>
		{/if}

		<!-- Trigger status panel -->
		{#if triggerStats.length > 0}
			<TriggerPanel stats={triggerStats} />
		{/if}

		<!-- Tabs -->
		<Tabs
			value={activeTab}
			onValueChange={onTabChange}
			class="flex min-h-0 flex-1 flex-col"
		>
			<TabsList
				variant="line"
				class="w-full justify-start gap-0 border-b border-edge bg-transparent px-0"
			>
				<TabsTrigger
					value="run"
					class="gap-1.5 rounded-none bg-transparent px-4 py-2 font-mono text-[13px] text-fg-faint transition-[color] duration-150 hover:text-fg-muted data-active:bg-transparent data-active:text-fg data-active:after:bg-accent-primary dark:data-active:bg-transparent dark:data-active:border-transparent"
				>
					<Play size={13} />
					Run
				</TabsTrigger>
				<TabsTrigger
					value="history"
					class="gap-1.5 rounded-none bg-transparent px-4 py-2 font-mono text-[13px] text-fg-faint transition-[color] duration-150 hover:text-fg-muted data-active:bg-transparent data-active:text-fg data-active:after:bg-accent-primary dark:data-active:bg-transparent dark:data-active:border-transparent"
				>
					<History size={13} />
					History
				</TabsTrigger>
				<TabsTrigger
					value="memory"
					class="gap-1.5 rounded-none bg-transparent px-4 py-2 font-mono text-[13px] text-fg-faint transition-[color] duration-150 hover:text-fg-muted data-active:bg-transparent data-active:text-fg data-active:after:bg-accent-primary dark:data-active:bg-transparent dark:data-active:border-transparent"
				>
					<Brain size={13} />
					Memory
				</TabsTrigger>
				<TabsTrigger
					value="ingest"
					class="gap-1.5 rounded-none bg-transparent px-4 py-2 font-mono text-[13px] text-fg-faint transition-[color] duration-150 hover:text-fg-muted data-active:bg-transparent data-active:text-fg data-active:after:bg-accent-primary dark:data-active:bg-transparent dark:data-active:border-transparent"
				>
					<Database size={13} />
					Ingest
				</TabsTrigger>
				<TabsTrigger
					value="config"
					class="gap-1.5 rounded-none bg-transparent px-4 py-2 font-mono text-[13px] text-fg-faint transition-[color] duration-150 hover:text-fg-muted data-active:bg-transparent data-active:text-fg data-active:after:bg-accent-primary dark:data-active:bg-transparent dark:data-active:border-transparent"
				>
					<Settings size={13} />
					Config
				</TabsTrigger>
				<TabsTrigger
					value="editor"
					class="gap-1.5 rounded-none bg-transparent px-4 py-2 font-mono text-[13px] text-fg-faint transition-[color] duration-150 hover:text-fg-muted data-active:bg-transparent data-active:text-fg data-active:after:bg-accent-primary dark:data-active:bg-transparent dark:data-active:border-transparent"
				>
					<FileCode size={13} />
					Editor
				</TabsTrigger>
			</TabsList>

			<TabsContent value="run" class="min-h-0 flex-1 pt-4">
				<RunPanel agentId={agentId} blockedReason={detail.error ?? detail.provider_warning ?? null} onRunCompleted={() => { runVersion++; refreshStats(); }} />
			</TabsContent>

			<TabsContent value="history" class="min-h-0 flex-1 pt-4">
				<HistoryTab agentName={detail.name} refreshKey={runVersion} />
			</TabsContent>

			<TabsContent value="memory" class="min-h-0 flex-1 pt-4">
				<MemoryTab agentId={agentId} hasMemory={!!detail.memory} />
			</TabsContent>

			<TabsContent value="ingest" class="min-h-0 flex-1 pt-4">
				<IngestTab agentId={agentId} hasIngest={!!detail.ingest} />
			</TabsContent>

			<TabsContent value="config" class="min-h-0 flex-1 pt-4">
				<div class="max-w-2xl">
					<ConfigPanel {detail} />
				</div>
			</TabsContent>

			<TabsContent value="editor" class="min-h-0 flex-1 pt-4">
				<EditorTab
					agentId={agentId}
					{yaml}
					path={agentPath}
					agentName={detail.name}
					onSaved={async () => {
						await reload();
						await refreshStats();
					}}
				/>
			</TabsContent>
		</Tabs>

		<ConfirmDeleteDialog
			entityName={detail.name}
			entityType="agent"
			bind:open={deleteDialogOpen}
			onConfirm={async () => {
				await deleteAgent(agentId);
				goto('/agents');
			}}
			onCancel={() => (deleteDialogOpen = false)}
		/>
	{:else}
		<p class="text-fg-faint">Agent not found</p>
	{/if}
</div>
