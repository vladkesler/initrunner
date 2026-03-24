<script lang="ts">
	import { page } from '$app/state';
	import { onMount } from 'svelte';
	import { fetchTeamDetail, fetchTeamYaml, validateTeam, saveTeamYaml } from '$lib/api/teams';
	import type { TeamDetail } from '$lib/api/types';
	import PersonaPipeline from '$lib/components/teams/PersonaPipeline.svelte';
	import TeamRunPanel from '$lib/components/teams/TeamRunPanel.svelte';
	import ConfigPanel from '$lib/components/teams/ConfigPanel.svelte';
	import YamlEditor from '$lib/components/ui/YamlEditor.svelte';
	import { Skeleton } from '$lib/components/ui/skeleton';
	import { ArrowLeft, Play, GitBranch, Settings, FileCode } from 'lucide-svelte';
	import { safeGet, safeSet } from '$lib/utils/storage';

	let detail: TeamDetail | null = $state(null);
	let yaml = $state('');
	let teamPath = $state('');
	let loading = $state(true);

	const teamId = $derived(page.params.id ?? '');

	// Tab persistence
	const tabKey = $derived(`team-tab-${teamId}`);
	let activeTab = $state('pipeline');

	const tabs = ['pipeline', 'run', 'config', 'editor'] as const;
	type Tab = (typeof tabs)[number];

	const tabMeta: Record<Tab, { label: string; icon: typeof Play }> = {
		pipeline: { label: 'Pipeline', icon: GitBranch },
		run: { label: 'Run', icon: Play },
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

		try {
			await reload();
		} catch {
			// not found
		} finally {
			loading = false;
		}
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
	{:else if detail}
		<!-- Header -->
		<div>
			<div class="flex items-center gap-3">
				<h1 class="text-xl font-semibold tracking-[-0.02em] text-fg">{detail.name}</h1>
				<span class="rounded-full border border-accent-primary/20 bg-accent-primary/10 px-2 py-0.5 font-mono text-[11px] text-accent-primary">
					{detail.strategy}
				</span>
				<span class="border border-edge bg-surface-1 px-2 py-0.5 font-mono text-[12px] text-fg-faint">
					{detail.personas.length} personas
				</span>
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
					<TeamRunPanel teamId={teamId} />
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
	{:else}
		<p class="text-[13px] text-fg-faint">Team not found.</p>
	{/if}
</div>
