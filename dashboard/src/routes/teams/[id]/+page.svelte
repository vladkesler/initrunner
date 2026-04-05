<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { onMount } from 'svelte';
	import { fetchTeamDetail, fetchTeamYaml, validateTeam, saveTeamYaml, deleteTeam, fetchTeamTimeline } from '$lib/api/teams';
	import type { TeamDetail } from '$lib/api/types';
	import { loadOr404 } from '$lib/utils/load';
	import { setCrumbs } from '$lib/stores/breadcrumb.svelte';

	$effect(() => { if (detail) setCrumbs([{ label: 'Teams', href: '/teams' }, { label: detail.name }]); });
	import PersonaPipeline from '$lib/components/teams/PersonaPipeline.svelte';
	import TeamRunPanel from '$lib/components/teams/TeamRunPanel.svelte';
	import TeamMemoryTab from '$lib/components/teams/TeamMemoryTab.svelte';
	import TeamIngestTab from '$lib/components/teams/TeamIngestTab.svelte';
	import ConfigPanel from '$lib/components/teams/ConfigPanel.svelte';
	import ConfirmDeleteDialog from '$lib/components/ui/ConfirmDeleteDialog.svelte';
	import YamlEditor from '$lib/components/ui/YamlEditor.svelte';
	import { Skeleton } from '$lib/components/ui/skeleton';
	import LoadError from '$lib/components/ui/LoadError.svelte';
	import { ArrowLeft, Play, GitBranch, Activity, Brain, Database, Settings, FileCode, Trash2 } from 'lucide-svelte';
	import TimelineView from '$lib/components/agents/TimelineView.svelte';
	import { safeGet, safeSet } from '$lib/utils/storage';

	let detail: TeamDetail | null = $state(null);
	let yaml = $state('');
	let teamPath = $state('');
	let loading = $state(true);
	let loadError = $state(false);
	let deleteDialogOpen = $state(false);
	let runVersion = $state(0);

	const teamId = $derived(page.params.id ?? '');

	// Tab persistence
	const tabKey = $derived(`team-tab-${teamId}`);
	let activeTab = $state('pipeline');

	const tabs = ['pipeline', 'run', 'timeline', 'memory', 'ingest', 'config', 'editor'] as const;
	type Tab = (typeof tabs)[number];

	const tabMeta: Record<Tab, { label: string; icon: typeof Play }> = {
		pipeline: { label: 'Pipeline', icon: GitBranch },
		run: { label: 'Run', icon: Play },
		timeline: { label: 'Timeline', icon: Activity },
		memory: { label: 'Memory', icon: Brain },
		ingest: { label: 'Ingest', icon: Database },
		config: { label: 'Config', icon: Settings },
		editor: { label: 'Editor', icon: FileCode }
	};

	async function reload() {
		const [d, y] = await Promise.all([
			fetchTeamDetail(teamId),
			fetchTeamYaml(teamId)
		]);
		detail = d;
		yaml = y.yaml;
		teamPath = y.path;
	}

	function switchTab(tab: string) {
		activeTab = tab;
		safeSet(tabKey, tab);
	}

	async function handleValidate(text: string) {
		const result = await validateTeam(text);
		return { issues: result.issues };
	}

	async function handleSave(text: string) {
		await saveTeamYaml(teamId, text);
	}

	onMount(async () => {
		// Restore saved tab
		const saved = safeGet(tabKey);
		if (saved && (tabs as readonly string[]).includes(saved)) {
			activeTab = saved;
		}

		const result = await loadOr404(() => reload(), 'Failed to load team');
		if (!result.ok && !result.notFound) loadError = true;
		loading = false;
	});
</script>

<div class="flex h-full flex-col gap-5">
	<!-- Back link -->
	<a
		href="/teams"
		class="inline-flex items-center gap-1.5 text-[13px] text-fg-faint transition-[color] duration-150 hover:text-fg-muted"
	>
		<ArrowLeft size={14} />
		Teams
	</a>

	{#if loading}
		<Skeleton class="h-6 w-48 bg-surface-1" />
		<Skeleton class="h-10 bg-surface-1" />
		<Skeleton class="h-64 bg-surface-1" />
	{:else if loadError}
		<LoadError message="Failed to load team" onRetry={() => location.reload()} />
	{:else if detail}
		<!-- Header -->
		<div>
			<div class="flex items-center gap-3">
				<h1 class="text-2xl font-semibold tracking-[-0.03em] text-fg">{detail.name}</h1>
				<span class="rounded-full border border-accent-primary/20 bg-accent-primary/10 px-2 py-0.5 font-mono text-[11px] text-accent-primary">
					{detail.strategy}{#if detail.debate} ({detail.debate.max_rounds} rounds){/if}
				</span>
				<span class="border border-edge bg-surface-1 px-2 py-0.5 font-mono text-[12px] text-fg-faint">
					{detail.personas.length} personas
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

		<!-- Tabs -->
		<div class="flex min-h-0 flex-1 flex-col">
			<div class="flex w-full justify-start gap-0 border-b border-edge">
				{#each tabs as tab}
					{@const meta = tabMeta[tab]}
					<button
						class="flex items-center gap-1.5 px-4 py-2 font-mono text-[13px] transition-[color] duration-150 {activeTab === tab
							? 'border-b-2 border-accent-primary text-fg'
							: 'text-fg-faint hover:text-fg-muted'}"
						onclick={() => switchTab(tab)}
					>
						<meta.icon size={13} />
						{meta.label}
					</button>
				{/each}
			</div>

			<div class="min-h-0 flex-1 pt-4">
				{#if activeTab === 'pipeline'}
					<div class="h-[calc(100vh-360px)] min-h-[400px]">
						<PersonaPipeline {detail} />
					</div>
				{:else if activeTab === 'run'}
					<TeamRunPanel teamId={teamId} {detail} onRunCompleted={() => { runVersion++; }} />
				{:else if activeTab === 'timeline'}
					<TimelineView fetchData={() => fetchTeamTimeline(teamId)} refreshKey={runVersion} />
				{:else if activeTab === 'memory'}
					<TeamMemoryTab teamId={teamId} hasMemory={!!(detail.shared_memory as Record<string, unknown>)?.enabled} />
				{:else if activeTab === 'ingest'}
					<TeamIngestTab teamId={teamId} hasIngest={!!(detail.shared_documents as Record<string, unknown>)?.enabled} />
				{:else if activeTab === 'config'}
					<div class="max-w-2xl">
						<ConfigPanel team={detail} />
					</div>
				{:else if activeTab === 'editor'}
					<YamlEditor
						{yaml}
						path={teamPath}
						entityName={detail.name}
						nameChangeWarning="Changing the team name will update the team ID. Existing references may break."
						validate={handleValidate}
						save={handleSave}
						onSaved={async () => {
							await reload();
						}}
					/>
				{/if}
			</div>
		</div>

		<ConfirmDeleteDialog
			entityName={detail.name}
			entityType="team"
			bind:open={deleteDialogOpen}
			onConfirm={async () => {
				await deleteTeam(teamId);
				goto('/teams');
			}}
			onCancel={() => (deleteDialogOpen = false)}
		/>
	{:else}
		<p class="text-[13px] text-fg-faint">Team not found.</p>
	{/if}
</div>
