<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { onMount } from 'svelte';
	import {
		fetchComposeDetail,
		fetchComposeYaml,
		fetchComposeEvents,
		fetchComposeStats,
		deleteCompose
	} from '$lib/api/compose';
	import type { ComposeDetail, ComposeStats, DelegateEvent } from '$lib/api/types';
	import { loadOr404 } from '$lib/utils/load';
	import { Skeleton } from '$lib/components/ui/skeleton';
	import LoadError from '$lib/components/ui/LoadError.svelte';
	import { Tabs, TabsContent, TabsList, TabsTrigger } from '$lib/components/ui/tabs';
	import ConfirmDeleteDialog from '$lib/components/ui/ConfirmDeleteDialog.svelte';
	import FlowCanvas from '$lib/components/compose/FlowCanvas.svelte';
	import RunPanel from '$lib/components/compose/RunPanel.svelte';
	import EventsTab from '$lib/components/compose/EventsTab.svelte';
	import ConfigPanel from '$lib/components/compose/ConfigPanel.svelte';
	import EditorTab from '$lib/components/compose/EditorTab.svelte';
	import {
		ArrowLeft,
		Activity,
		CheckCircle,
		Layers,
		AlertTriangle,
		Play,
		GitBranch,
		List,
		Settings,
		FileCode,
		Trash2
	} from 'lucide-svelte';

	let detail: ComposeDetail | null = $state(null);
	let yaml = $state('');
	let composePath = $state('');
	let stats: ComposeStats | null = $state(null);
	let events = $state<DelegateEvent[]>([]);
	let loading = $state(true);
	let loadError = $state(false);
	let statsLoading = $state(true);
	let eventsLoading = $state(true);
	let deleteDialogOpen = $state(false);

	const composeId = $derived(page.params.id ?? '');

	// Tab persistence
	const tabKey = $derived(`compose-tab-${composeId}`);
	let activeTab = $state('run');

	const serviceNames = $derived(detail ? detail.services.map((s) => s.name) : []);

	// Stats derived values
	const deliveryRate = $derived.by(() => {
		if (!stats || stats.total_events === 0) return 0;
		return Math.round(((stats.by_status.delivered ?? 0) / stats.total_events) * 100);
	});

	const deliveryRateColor = $derived.by(() => {
		if (deliveryRate >= 90) return 'text-ok';
		if (deliveryRate >= 70) return 'text-warn';
		return 'text-fail';
	});

	const issueCount = $derived.by(() => {
		if (!stats) return 0;
		let count = 0;
		for (const [status, n] of Object.entries(stats.by_status)) {
			if (status !== 'delivered') count += n;
		}
		return count;
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
		const [d, y] = await Promise.all([
			fetchComposeDetail(composeId),
			fetchComposeYaml(composeId)
		]);
		detail = d;
		yaml = y.yaml;
		composePath = y.path;
	}

	onMount(async () => {
		// Restore saved tab
		try {
			const saved = localStorage.getItem(tabKey);
			if (saved && ['run', 'graph', 'events', 'config', 'editor'].includes(saved)) {
				activeTab = saved;
			}
		} catch {
			// ignore
		}

		// Stage 1: detail + yaml (parallel)
		const result = await loadOr404(() => reload(), 'Failed to load composition');
		if (!result.ok && !result.notFound) loadError = true;
		loading = false;

		// Stage 2: stats + events (parallel, needs compose loaded)
		if (detail) {
			const [s, e] = await Promise.allSettled([
				fetchComposeStats(composeId),
				fetchComposeEvents(composeId)
			]);
			if (s.status === 'fulfilled') stats = s.value;
			if (e.status === 'fulfilled') events = e.value;
		}
		statsLoading = false;
		eventsLoading = false;
	});
</script>

<div class="flex h-full flex-col gap-5">
	<!-- Back link -->
	<a
		href="/compose"
		class="inline-flex items-center gap-1.5 text-[13px] text-fg-faint transition-[color] duration-150 hover:text-fg-muted"
	>
		<ArrowLeft size={14} />
		Compose
	</a>

	{#if loading}
		<Skeleton class="h-6 w-48 bg-surface-1" />
		<Skeleton class="h-10 bg-surface-1" />
		<Skeleton class="h-64 bg-surface-1" />
	{:else if loadError}
		<LoadError message="Failed to load composition" onRetry={() => location.reload()} />
	{:else if detail}
		<!-- Header -->
		<div>
			<div class="flex items-center gap-3">
				<h1 class="text-xl font-semibold tracking-[-0.02em] text-fg">{detail.name}</h1>
				<span class="border border-edge bg-surface-1 px-2 py-0.5 font-mono text-[12px] text-fg-faint">
					{detail.services.length} services
				</span>
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
							{stats.total_events.toLocaleString()}
						</div>
						<div class="text-[12px] text-fg-faint">events</div>
					</div>
				</div>
				<div
					class="card-surface flex items-center gap-2.5 bg-surface-1 px-3 py-2 animate-fade-in-up"
					style="animation-delay: 60ms"
				>
					<CheckCircle size={14} class="shrink-0 {deliveryRateColor}" />
					<div>
						<div
							class="font-mono text-[18px] font-semibold tracking-[-0.02em] text-fg"
							style="font-variant-numeric: tabular-nums"
						>
							{deliveryRate}%
						</div>
						<div class="text-[12px] text-fg-faint">delivery</div>
					</div>
				</div>
				<div
					class="card-surface flex items-center gap-2.5 bg-surface-1 px-3 py-2 animate-fade-in-up"
					style="animation-delay: 120ms"
				>
					<Layers size={14} class="shrink-0 text-accent-primary/60" />
					<div>
						<div
							class="font-mono text-[18px] font-semibold tracking-[-0.02em] text-fg"
							style="font-variant-numeric: tabular-nums"
						>
							{detail.services.length}
						</div>
						<div class="text-[12px] text-fg-faint">services</div>
					</div>
				</div>
				<div
					class="card-surface flex items-center gap-2.5 bg-surface-1 px-3 py-2 animate-fade-in-up"
					style="animation-delay: 180ms"
				>
					<AlertTriangle size={14} class="shrink-0 {issueCount > 0 ? 'text-warn' : 'text-fg-faint'}" />
					<div>
						<div
							class="font-mono text-[18px] font-semibold tracking-[-0.02em] text-fg"
							style="font-variant-numeric: tabular-nums"
						>
							{issueCount.toLocaleString()}
						</div>
						<div class="text-[12px] text-fg-faint">issues</div>
					</div>
				</div>
			</div>
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
					value="graph"
					class="gap-1.5 rounded-none bg-transparent px-4 py-2 font-mono text-[13px] text-fg-faint transition-[color] duration-150 hover:text-fg-muted data-active:bg-transparent data-active:text-fg data-active:after:bg-accent-primary dark:data-active:bg-transparent dark:data-active:border-transparent"
				>
					<GitBranch size={13} />
					Graph
				</TabsTrigger>
				<TabsTrigger
					value="events"
					class="gap-1.5 rounded-none bg-transparent px-4 py-2 font-mono text-[13px] text-fg-faint transition-[color] duration-150 hover:text-fg-muted data-active:bg-transparent data-active:text-fg data-active:after:bg-accent-primary dark:data-active:bg-transparent dark:data-active:border-transparent"
				>
					<List size={13} />
					Events
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
				<RunPanel {composeId} {detail} onRunCompleted={async () => {
					const [s, e] = await Promise.allSettled([
						fetchComposeStats(composeId),
						fetchComposeEvents(composeId)
					]);
					if (s.status === 'fulfilled') stats = s.value;
					if (e.status === 'fulfilled') events = e.value;
				}} />
			</TabsContent>

			<TabsContent value="graph" class="min-h-0 flex-1 pt-4">
				<div class="h-[calc(100vh-360px)] min-h-[400px]">
					<FlowCanvas {detail} />
				</div>
			</TabsContent>

			<TabsContent value="events" class="min-h-0 flex-1 pt-4">
				<EventsTab {events} {serviceNames} loading={eventsLoading} />
			</TabsContent>

			<TabsContent value="config" class="min-h-0 flex-1 pt-4">
				<div class="max-w-2xl">
					<ConfigPanel {detail} />
				</div>
			</TabsContent>

			<TabsContent value="editor" class="min-h-0 flex-1 pt-4">
				<EditorTab
					{composeId}
					{yaml}
					path={composePath}
					composeName={detail.name}
					onSaved={async () => {
						await reload();
					}}
				/>
			</TabsContent>
		</Tabs>

		<ConfirmDeleteDialog
			entityName={detail.name}
			entityType="compose"
			bind:open={deleteDialogOpen}
			onConfirm={async () => {
				await deleteCompose(composeId);
				goto('/compose');
			}}
			onCancel={() => (deleteDialogOpen = false)}
		/>
	{:else}
		<p class="text-[13px] text-fg-faint">Composition not found.</p>
	{/if}
</div>
