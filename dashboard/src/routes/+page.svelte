<script lang="ts">
	import { onMount } from 'svelte';
	import { listAgents } from '$lib/api/agents';
	import { queryAudit } from '$lib/api/audit';
	import { fetchAuditStats } from '$lib/api/system';
	import { request } from '$lib/api/client';
	import type { AgentSummary, AuditRecord, AuditStats, HealthStatus } from '$lib/api/types';
	import { Skeleton } from '$lib/components/ui/skeleton';
	import { Plus, BookOpen, Stethoscope, Activity, CheckCircle, Timer, AlertTriangle, ArrowUpRight, Workflow, Users, ExternalLink, TrendingDown, TrendingUp } from 'lucide-svelte';
	import CapabilityGlyph from '$lib/components/agents/CapabilityGlyph.svelte';
	import { fetchComposeList } from '$lib/api/compose';
	import { fetchTeamList } from '$lib/api/teams';
	import { getBuilderOptions, getStarters, type BuilderOptions, type StarterInfo } from '$lib/api/builder';
	import type { ComposeSummary, TeamSummary } from '$lib/api/types';
	import { toast } from '$lib/stores/toast.svelte';
	import ProviderStatusBanner from '$lib/components/ui/ProviderStatusBanner.svelte';
	import StarterCard from '$lib/components/ui/StarterCard.svelte';
	import CapabilityChips from '$lib/components/ui/CapabilityChips.svelte';

	let agents = $state<AgentSummary[]>([]);
	let composes = $state<ComposeSummary[]>([]);
	let teams = $state<TeamSummary[]>([]);
	let recentAudit = $state<AuditRecord[]>([]);
	let stats = $state<AuditStats | null>(null);
	let version = $state('');
	let loading = $state(true);
	let builderOptions = $state<BuilderOptions | null>(null);
	let starters = $state<StarterInfo[]>([]);

	const errorAgents = $derived(agents.filter((a) => a.error));
	const isEmpty = $derived(agents.length === 0 && composes.length === 0 && teams.length === 0);
	const agentIdByName = $derived(new Map(agents.map((a) => [a.name, a.id])));
	const agentByName = $derived(new Map(agents.map((a) => [a.name, a])));

	// Recent success count from last 10 fetched records (sample, not census)
	const recentSuccessCount = $derived(recentAudit.filter((r) => r.success).length);
	const recentSuccessRate = $derived(
		recentAudit.length > 0 ? Math.round((recentSuccessCount / recentAudit.length) * 100) : null
	);

	// Success divergence: does the last-10 sample diverge from the all-time rate?
	const successDiverging = $derived.by(() => {
		if (!stats || recentSuccessRate === null) return 'none' as const;
		const diff = recentSuccessRate - stats.success_rate;
		if (diff <= -15) return 'worse' as const;
		if (diff >= 15) return 'better' as const;
		return 'none' as const;
	});

	// Tokens per run (all-time average from stats)
	const tokensPerRun = $derived(
		stats && stats.total_runs > 0 ? Math.round(stats.total_tokens / stats.total_runs) : 0
	);

	// Grouped activity feed (consecutive same-agent collapse)
	const groupedActivity = $derived.by(() => {
		const groups: Array<{
			agentName: string;
			runs: AuditRecord[];
			agentId: string | undefined;
			hasFailure: boolean;
		}> = [];
		for (const run of recentAudit) {
			const last = groups.at(-1);
			if (last && last.agentName === run.agent_name) {
				last.runs.push(run);
				if (!run.success) last.hasFailure = true;
			} else {
				groups.push({
					agentName: run.agent_name,
					runs: [run],
					agentId: agentIdByName.get(run.agent_name),
					hasFailure: !run.success
				});
			}
		}
		return groups;
	});

	function timeAgo(ts: string): string {
		try {
			const diff = Date.now() - new Date(ts).getTime();
			const mins = Math.floor(diff / 60000);
			if (mins < 1) return 'just now';
			if (mins < 60) return `${mins}m ago`;
			const hrs = Math.floor(mins / 60);
			if (hrs < 24) return `${hrs}h ago`;
			const days = Math.floor(hrs / 24);
			return `${days}d ago`;
		} catch {
			return '';
		}
	}

	function truncate(text: string, len: number): string {
		if (!text) return '';
		return text.length > len ? text.slice(0, len) + '\u2026' : text;
	}

	function formatDuration(ms: number): string {
		if (ms < 1000) return `${ms}ms`;
		const s = ms / 1000;
		if (s < 60) return `${s.toFixed(1)}s`;
		const m = Math.floor(s / 60);
		const rem = Math.round(s % 60);
		return `${m}m ${rem}s`;
	}

	function formatTokens(n: number): string {
		if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
		if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
		return `${n}`;
	}

	onMount(async () => {
		try {
			const [a, c, t, audit, s, health, opts, st] = await Promise.all([
				listAgents(),
				fetchComposeList().catch(() => [] as ComposeSummary[]),
				fetchTeamList().catch(() => [] as TeamSummary[]),
				queryAudit({ limit: 10, exclude_trigger_types: ['compose', 'delegate', 'team'] }),
				fetchAuditStats(),
				request<HealthStatus>('/api/health'),
				getBuilderOptions().catch(() => null as BuilderOptions | null),
				getStarters().catch(() => ({ starters: [] }))
			]);
			agents = a;
			composes = c;
			teams = t;
			recentAudit = audit;
			stats = s;
			version = health.version;
			builderOptions = opts;
			starters = st.starters;
		} catch {
			toast.error('Failed to connect to API server');
		} finally {
			loading = false;
		}
	});

	async function reloadProviders() {
		try {
			builderOptions = await getBuilderOptions();
		} catch {
			toast.error('Failed to refresh provider status');
		}
	}
</script>

<div>
	{#if loading}
		<div class="space-y-4">
			<Skeleton class="h-6 w-48 bg-surface-1" />
			<Skeleton class="h-40 bg-surface-1" />
			<Skeleton class="h-64 bg-surface-1" />
		</div>
	{:else if isEmpty}
		<!-- Zero state: Onboarding -->
		<div class="space-y-8 py-8">
			<!-- Header -->
			<div class="flex items-center gap-3">
				<h1 class="text-xl font-semibold tracking-[-0.02em] text-fg">Welcome to InitRunner</h1>
				{#if version}
					<span class="border border-edge bg-surface-1 px-2 py-0.5 font-mono text-[12px] text-fg-faint">v{version}</span>
				{/if}
			</div>

			<!-- Provider status -->
			{#if builderOptions}
				<ProviderStatusBanner
					providerStatus={builderOptions.provider_status}
					detectedProvider={builderOptions.detected_provider}
					onConfigured={reloadProviders}
				/>
			{/if}

			<!-- Primary CTAs -->
			<div class="flex flex-wrap gap-4">
				<a
					href="/agents/new"
					class="flex items-center gap-2 rounded-full bg-accent-primary px-6 py-2.5 text-[13px] font-medium text-surface-0 transition-[background-color,box-shadow] duration-150 hover:bg-accent-primary-hover hover:shadow-[0_0_16px_oklch(0.91_0.20_128/0.25)]"
				>
					<Plus size={16} />
					Create an Agent
				</a>
				<a
					href="https://www.initrunner.ai/docs/quickstart"
					target="_blank"
					rel="noopener"
					class="flex items-center gap-2 rounded-full border border-edge bg-surface-1 px-6 py-2.5 text-[13px] font-medium text-fg-muted transition-[color,background-color,border-color] duration-150 hover:bg-surface-2 hover:text-fg hover:border-accent-primary/20"
				>
					<BookOpen size={16} />
					Read the Quickstart
					<ExternalLink size={12} />
				</a>
			</div>

			<!-- Starter templates -->
			{#if starters.length > 0}
				<div>
					<h2 class="mb-3 font-mono text-[12px] font-medium uppercase tracking-[0.1em] text-fg-faint">
						Start from a template
					</h2>
					<div class="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
						{#each starters.slice(0, 6) as starter, i}
							<StarterCard {starter} index={i} />
						{/each}
					</div>
					<a
						href="/agents/new"
						class="mt-3 inline-block text-[13px] text-fg-faint transition-[color] duration-150 hover:text-fg-muted"
					>
						View all templates
					</a>
				</div>
			{/if}

			<!-- Explore capabilities -->
			<div>
				<h2 class="mb-3 font-mono text-[12px] font-medium uppercase tracking-[0.1em] text-fg-faint">
					Explore
				</h2>
				<CapabilityChips />
				<a
					href="https://www.initrunner.ai/docs/quickstart"
					target="_blank"
					rel="noopener"
					class="mt-3 inline-flex items-center gap-1 text-[13px] text-fg-faint transition-[color] duration-150 hover:text-fg-muted"
				>
					Full documentation
					<ExternalLink size={12} />
				</a>
			</div>
		</div>
	{:else}
		<!-- Main dashboard grid -->
		<div class="grid grid-cols-1 gap-4 lg:grid-cols-3">
			<!-- Command bar -->
			<div class="flex flex-wrap items-center justify-between gap-3 lg:col-span-3">
				<div class="flex items-center gap-3">
					<h1 class="text-xl font-semibold tracking-[-0.02em] text-fg">Launchpad</h1>
					{#if version}
						<span class="border border-edge bg-surface-1 px-2 py-0.5 font-mono text-[12px] text-fg-faint">v{version}</span>
					{/if}
				</div>
				<div class="flex items-center gap-3">
					<a
						href="/agents/new"
						class="flex items-center gap-2 rounded-full bg-accent-primary px-5 py-2 text-[13px] font-medium text-surface-0 transition-[background-color,box-shadow] duration-150 hover:bg-accent-primary-hover hover:shadow-[0_0_16px_oklch(0.91_0.20_128/0.25)]"
					>
						<Plus size={14} />
						New Agent
					</a>
					<a
						href="/compose/new"
						class="flex items-center gap-2 rounded-full border border-accent-primary/30 bg-accent-primary/10 px-5 py-2 text-[13px] font-medium text-accent-primary transition-[background-color] duration-150 hover:bg-accent-primary/20"
					>
						<Workflow size={14} />
						New Compose
					</a>
					<a
						href="/teams/new"
						class="flex items-center gap-2 rounded-full border border-accent-primary/30 bg-accent-primary/10 px-5 py-2 text-[13px] font-medium text-accent-primary transition-[background-color] duration-150 hover:bg-accent-primary/20"
					>
						<Users size={14} />
						New Team
					</a>
					<a
						href="/system"
						class="flex items-center gap-2 rounded-full border border-edge bg-surface-1 px-5 py-2 text-[13px] font-medium text-fg-muted transition-[color,background-color,border-color] duration-150 hover:bg-surface-2 hover:text-fg hover:border-accent-primary/20"
					>
						<Stethoscope size={14} />
						Run Doctor
					</a>
				</div>
			</div>

			<!-- Stats strip -->
			{#if stats}
				<div class="grid grid-cols-2 gap-3 lg:col-span-3 lg:grid-cols-4">
					<!-- Total Runs -->
					<div class="card-surface flex items-center gap-3 bg-surface-1 px-4 py-3 animate-fade-in-up" style="animation-delay: 0ms">
						<Activity size={16} class="shrink-0 text-accent-primary/60" />
						<div>
							<div class="font-mono text-[22px] font-semibold tracking-[-0.02em] text-fg" style="font-variant-numeric: tabular-nums">{stats.total_runs.toLocaleString()}</div>
							<div class="text-[12px] text-fg-faint">total runs</div>
							{#if recentAudit.length > 0}
								<div class="mt-0.5 font-mono text-[11px] text-fg-faint">
									<span class="text-accent-primary">{recentSuccessCount}</span>/{recentAudit.length} recent ok
								</div>
							{/if}
						</div>
					</div>
					<!-- Success Rate -->
					<div
						class="flex items-center gap-3 bg-surface-1 px-4 py-3 animate-fade-in-up {stats.success_rate < 70 ? 'card-surface-error' : 'card-surface'}"
						style="animation-delay: 60ms{stats.success_rate >= 70 && stats.success_rate < 90 ? '; border-top-color: var(--color-warn)' : ''}"
					>
						<CheckCircle size={16} class="shrink-0 {stats.success_rate >= 90 ? 'text-ok' : stats.success_rate >= 70 ? 'text-warn' : 'text-fail'}" />
						<div>
							<div class="font-mono text-[22px] font-semibold tracking-[-0.02em] text-fg" style="font-variant-numeric: tabular-nums">{stats.success_rate}%</div>
							<div class="text-[12px] text-fg-faint">success rate</div>
							{#if recentSuccessRate !== null && successDiverging !== 'none'}
								<div class="mt-0.5 flex items-center gap-1 font-mono text-[11px]">
									{#if successDiverging === 'worse'}
										<TrendingDown size={10} class="text-fail" />
										<span class="text-fail">last 10: {recentSuccessRate}%</span>
									{:else}
										<TrendingUp size={10} class="text-ok" />
										<span class="text-ok">last 10: {recentSuccessRate}%</span>
									{/if}
								</div>
							{/if}
						</div>
					</div>
					<!-- Tokens / Run -->
					<div class="card-surface flex items-center gap-3 bg-surface-1 px-4 py-3 animate-fade-in-up" style="animation-delay: 120ms">
						<Activity size={16} class="shrink-0 text-accent-primary/60" />
						<div>
							<div class="font-mono text-[22px] font-semibold tracking-[-0.02em] text-fg" style="font-variant-numeric: tabular-nums">~{formatTokens(tokensPerRun)}</div>
							<div class="text-[12px] text-fg-faint">tokens / run</div>
						</div>
					</div>
					<!-- Avg Duration -->
					<div class="card-surface flex items-center gap-3 bg-surface-1 px-4 py-3 animate-fade-in-up" style="animation-delay: 180ms">
						<Timer size={16} class="shrink-0 text-accent-primary/60" />
						<div>
							<div class="font-mono text-[22px] font-semibold tracking-[-0.02em] text-fg" style="font-variant-numeric: tabular-nums">{formatDuration(stats.avg_duration_ms)}</div>
							<div class="text-[12px] text-fg-faint">avg duration</div>
						</div>
					</div>
				</div>
			{/if}

			<!-- Failing agents -->
			{#if errorAgents.length > 0}
				<div class="lg:col-span-3">
					<h2 class="mb-3 flex items-center gap-2 font-mono text-[12px] font-medium uppercase tracking-[0.1em] text-fail">
						<AlertTriangle size={12} />
						Failing Agents
					</h2>
					<div class="space-y-1">
						{#each errorAgents as agent}
							<a
								href="/agents/{agent.id}"
								class="card-surface-error flex items-baseline gap-3 bg-surface-1 px-4 py-3 transition-[background-color] duration-150 hover:bg-surface-2"
							>
								<span class="text-[13px] font-medium text-fg">{agent.name}</span>
								<span class="truncate font-mono text-sm text-fail">{agent.error}</span>
							</a>
						{/each}
					</div>
				</div>
			{/if}

			<!-- Fleet + Feed columns -->
			<div class="flex flex-col gap-4 lg:col-span-3 lg:flex-row lg:items-start">
				<!-- Left column: Fleet + Orchestration -->
				<div class="min-w-0 lg:flex-[2]">
				{#if stats && stats.top_agents.length > 0}
						<div class="mb-3 flex items-baseline justify-between">
							<h2 class="font-mono text-[12px] font-medium uppercase tracking-[0.1em] text-fg-faint">Agent Fleet</h2>
							<a href="/agents" class="text-[12px] text-fg-faint transition-[color] duration-150 hover:text-fg-muted">View all</a>
						</div>
						<div class="space-y-1.5">
							{#each stats.top_agents as topAgent, i}
								{@const agent = agentByName.get(topAgent.name)}
								{@const agentId = agentIdByName.get(topAgent.name)}
								{@const hasError = agent?.error != null}
								{@const isRich = agent != null && agent.features.length >= 4}
								<a
									href={agentId ? `/agents/${agentId}` : '/agents'}
									class="group relative block overflow-hidden bg-surface-1 px-4 py-3 transition-[background-color,border-color] duration-200 hover:bg-surface-2
										{hasError ? 'card-surface-error' : 'card-surface'}
										{isRich && !hasError ? 'glow-lime-subtle' : ''}
										animate-fade-in-up"
									style="animation-delay: {i * 40}ms"
								>
									<!-- Hover gradient wash -->
									<div class="pointer-events-none absolute inset-0 bg-gradient-to-br from-accent-primary/[0.04] via-transparent to-transparent opacity-0 transition-opacity duration-200 group-hover:opacity-100"></div>

									<div class="relative flex items-center gap-3">
										<div class="w-[14px] shrink-0">
											{#if agent}
												<CapabilityGlyph features={agent.features} />
											{/if}
										</div>
										<span class="font-mono text-[13px] text-fg-muted transition-[color] duration-150 group-hover:text-accent-primary">{topAgent.name}</span>
										{#if hasError}
											<AlertTriangle size={12} class="shrink-0 text-fail" />
										{/if}
										<span class="ml-auto flex items-center gap-4 font-mono text-[12px] text-fg-faint">
											<span style="font-variant-numeric: tabular-nums">{topAgent.count} runs</span>
											<span style="font-variant-numeric: tabular-nums">{formatDuration(topAgent.avg_duration_ms)}</span>
										</span>
										<ArrowUpRight size={12} class="shrink-0 text-fg-faint opacity-0 transition-opacity duration-150 group-hover:opacity-100" />
									</div>
								</a>
							{/each}
						</div>
				{/if}

				<!-- Orchestration (in left column, below fleet) -->
				{#if composes.length > 0 || teams.length > 0}
					<div class="glow-cyan mt-6 p-4">
						<h2 class="mb-4 font-mono text-[12px] font-medium uppercase tracking-[0.1em] text-fg-faint">
							Orchestration
						</h2>
						<div class="space-y-5">
							{#if composes.length > 0}
								<div>
									<div class="mb-2 flex items-baseline justify-between">
										<h3 class="font-mono text-[11px] font-medium uppercase tracking-[0.12em] text-accent-secondary">Compositions</h3>
										<a href="/compose" class="text-[12px] text-fg-faint transition-[color] duration-150 hover:text-fg-muted">View all</a>
									</div>
									<div class="space-y-1.5">
										{#each composes.slice(0, 2) as compose, i}
											<a
												href="/compose/{compose.id}"
												class="card-surface flex items-center justify-between bg-surface-1 px-4 py-3 transition-[border-color,background-color] duration-150 hover:bg-accent-secondary/[0.03] animate-fade-in-up"
												style="animation-delay: {i * 40}ms"
											>
												<div class="flex items-center gap-2.5">
													<Workflow size={14} class="shrink-0 text-accent-secondary" />
													<span class="font-mono text-[13px] text-fg-muted">{compose.name}</span>
												</div>
												<span class="rounded-full border border-accent-secondary/20 bg-accent-secondary/10 px-2 py-0.5 font-mono text-[10px] text-accent-secondary">{compose.service_count} svc</span>
											</a>
										{/each}
									</div>
								</div>
							{/if}
							{#if teams.length > 0}
								<div>
									<div class="mb-2 flex items-baseline justify-between">
										<h3 class="font-mono text-[11px] font-medium uppercase tracking-[0.12em] text-accent-secondary">Teams</h3>
										<a href="/teams" class="text-[12px] text-fg-faint transition-[color] duration-150 hover:text-fg-muted">View all</a>
									</div>
									<div class="space-y-1.5">
										{#each teams.slice(0, 2) as team, i}
											<a
												href="/teams/{team.id}"
												class="card-surface flex items-center justify-between bg-surface-1 px-4 py-3 transition-[border-color,background-color] duration-150 hover:bg-accent-secondary/[0.03] animate-fade-in-up"
												style="animation-delay: {i * 40}ms"
											>
												<div class="flex items-center gap-2.5">
													<Users size={14} class="shrink-0 text-accent-secondary" />
													<span class="font-mono text-[13px] text-fg-muted">{team.name}</span>
												</div>
												<div class="flex shrink-0 items-center gap-2.5">
													<span class="rounded-full border border-accent-secondary/20 bg-accent-secondary/10 px-2 py-0.5 font-mono text-[10px] text-accent-secondary">{team.strategy}</span>
													<span class="font-mono text-[11px] text-fg-faint">{team.persona_count} personas</span>
												</div>
											</a>
										{/each}
									</div>
								</div>
							{/if}
						</div>
					</div>
				{/if}
				</div>

				<!-- Right column: Recent Runs -->
				{#if recentAudit.length > 0}
					<div class="min-w-0 lg:flex-1">
						<div class="mb-3 flex items-baseline justify-between">
							<h2 class="font-mono text-[12px] font-medium uppercase tracking-[0.1em] text-fg-faint">Recent Runs</h2>
							<a href="/audit" class="text-[12px] text-fg-faint transition-[color] duration-150 hover:text-fg-muted">View all</a>
						</div>
						<div>
							{#each groupedActivity as group, gi}
								{@const isSingle = group.runs.length === 1}
								{@const latestRun = group.runs[0]}
								{@const oldestRun = group.runs[group.runs.length - 1]}
								<div class={gi > 0 ? 'border-t border-edge-subtle pt-1.5 mt-1.5' : ''}>
									<a
										href={group.agentId ? `/agents/${group.agentId}` : '/agents'}
										class="group flex items-center gap-3 px-3 py-1.5 transition-[background-color] duration-150 hover:bg-surface-1"
									>
										<span
											class="inline-block h-1.5 w-1.5 shrink-0 rounded-full"
											class:bg-ok={!group.hasFailure}
											class:bg-fail={group.hasFailure}
											style="box-shadow: 0 0 4px {group.hasFailure ? 'var(--color-fail)' : 'var(--color-ok)'}"
										></span>
										<span class="font-mono text-[13px] text-fg-muted transition-[color] duration-150 group-hover:text-accent-primary">{group.agentName}</span>
										{#if !isSingle}
											<span class="rounded-full border border-edge bg-surface-2 px-1.5 py-0.5 font-mono text-[10px] text-fg-faint">x{group.runs.length}</span>
										{/if}
										<span class="ml-auto shrink-0 font-mono text-[12px] text-fg-faint">
											{#if isSingle}
												{timeAgo(latestRun.timestamp)}
											{:else}
												{timeAgo(oldestRun.timestamp)}-{timeAgo(latestRun.timestamp)}
											{/if}
										</span>
									</a>
									{#if isSingle && latestRun.duration_ms}
										<div class="px-3 pb-0.5 font-mono text-[11px] text-fg-faint" style="padding-left: calc(0.75rem + 6px + 0.75rem)">
											{formatDuration(latestRun.duration_ms)}
										</div>
									{/if}
									{#if group.hasFailure}
										{@const failedRun = group.runs.find((r) => !r.success)}
										{#if failedRun?.error}
											<div class="px-3 pb-0.5 font-mono text-[11px] text-fail" style="padding-left: calc(0.75rem + 6px + 0.75rem)">
												{truncate(failedRun.error, 40)}
											</div>
										{/if}
									{/if}
								</div>
							{/each}
						</div>
					</div>
				{:else}
					<div class="py-16 text-center text-[13px] text-fg-faint lg:flex-1">
						No runs yet. Run an agent to see activity here.
					</div>
				{/if}
			</div>
		</div>
	{/if}
</div>
