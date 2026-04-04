<script lang="ts">
	import { onMount } from 'svelte';
	import { listAgents } from '$lib/api/agents';
	import { queryAudit } from '$lib/api/audit';
	import { fetchAuditStats } from '$lib/api/system';
	import { getMcpHealthSummary } from '$lib/api/mcp';
	import { request } from '$lib/api/client';
	import type { AgentSummary, AuditRecord, AuditStats, HealthStatus, McpHealthSummary } from '$lib/api/types';
	import { Skeleton } from '$lib/components/ui/skeleton';
	import { Plus, BookOpen, Stethoscope, AlertTriangle, ArrowUpRight, Workflow, Users, ExternalLink, TrendingDown, TrendingUp } from 'lucide-svelte';
	import CapabilityGlyph from '$lib/components/agents/CapabilityGlyph.svelte';
	import { fetchFlowList } from '$lib/api/flow';
	import { fetchTeamList } from '$lib/api/teams';
	import { getBuilderOptions, getStarters, type BuilderOptions, type StarterInfo } from '$lib/api/builder';
	import type { FlowSummary, TeamSummary } from '$lib/api/types';
	import { toast } from '$lib/stores/toast.svelte';
	import { setCrumbs } from '$lib/stores/breadcrumb.svelte';
	import ProviderStatusBanner from '$lib/components/ui/ProviderStatusBanner.svelte';
	import StarterCard from '$lib/components/ui/StarterCard.svelte';
	import CapabilityChips from '$lib/components/ui/CapabilityChips.svelte';

	let agents = $state<AgentSummary[]>([]);
	let flows = $state<FlowSummary[]>([]);
	let teams = $state<TeamSummary[]>([]);
	let recentAudit = $state<AuditRecord[]>([]);
	let stats = $state<AuditStats | null>(null);
	let version = $state('');
	let loading = $state(true);
	let builderOptions = $state<BuilderOptions | null>(null);
	let starters = $state<StarterInfo[]>([]);
	let mcpHealth = $state<McpHealthSummary | null>(null);

	const errorAgents = $derived(agents.filter((a) => a.error));
	const isEmpty = $derived(agents.length === 0 && flows.length === 0 && teams.length === 0);
	const agentIdByName = $derived(new Map(agents.map((a) => [a.name, a.id])));
	const agentByName = $derived(new Map(agents.map((a) => [a.name, a])));

	const recentSuccessCount = $derived(recentAudit.filter((r) => r.success).length);
	const recentSuccessRate = $derived(
		recentAudit.length > 0 ? Math.round((recentSuccessCount / recentAudit.length) * 100) : null
	);

	const successDiverging = $derived.by(() => {
		if (!stats || recentSuccessRate === null) return 'none' as const;
		const diff = recentSuccessRate - stats.success_rate;
		if (diff <= -15) return 'worse' as const;
		if (diff >= 15) return 'better' as const;
		return 'none' as const;
	});

	const tokensPerRun = $derived(
		stats && stats.total_runs > 0 ? Math.round(stats.total_tokens / stats.total_runs) : 0
	);

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

	$effect(() => {
		setCrumbs([{ label: 'Launchpad' }]);
	});

	onMount(async () => {
		try {
			const [a, c, t, audit, s, health, opts, st, mh] = await Promise.all([
				listAgents(),
				fetchFlowList().catch(() => [] as FlowSummary[]),
				fetchTeamList().catch(() => [] as TeamSummary[]),
				queryAudit({ limit: 10, exclude_trigger_types: ['flow', 'delegate', 'team'] }),
				fetchAuditStats(),
				request<HealthStatus>('/api/health'),
				getBuilderOptions().catch(() => null as BuilderOptions | null),
				getStarters().catch(() => ({ starters: [] })),
				getMcpHealthSummary().catch(() => null as McpHealthSummary | null)
			]);
			agents = a;
			flows = c;
			teams = t;
			recentAudit = audit;
			stats = s;
			version = health.version;
			builderOptions = opts;
			starters = st.starters;
			mcpHealth = mh;
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
				<h1 class="text-2xl font-semibold tracking-[-0.03em] text-fg">Welcome to InitRunner</h1>
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
					class="flex items-center gap-2 rounded-[2px] bg-accent-primary px-6 py-2.5 text-[13px] font-medium text-surface-0 transition-[background-color] duration-150 hover:bg-accent-primary-hover"
				>
					<Plus size={16} />
					Create an Agent
				</a>
				<a
					href="https://www.initrunner.ai/docs/quickstart"
					target="_blank"
					rel="noopener"
					class="flex items-center gap-2 rounded-[2px] border border-edge bg-transparent px-6 py-2.5 text-[13px] font-medium text-fg-muted transition-[color,border-color] duration-150 hover:border-accent-primary-dim hover:text-fg"
				>
					<BookOpen size={16} />
					Read the Quickstart
					<ExternalLink size={12} />
				</a>
			</div>

			<!-- Starter templates -->
			{#if starters.length > 0}
				<div>
					<h2 class="section-label mb-3">Start from a template</h2>
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
				<h2 class="section-label mb-3">Explore</h2>
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
		<div class="grid grid-cols-1 gap-6 lg:grid-cols-3">
			<!-- Command bar -->
			<div class="flex flex-wrap items-center justify-between gap-3 lg:col-span-3">
				<div class="flex items-center gap-3">
					<h1 class="text-2xl font-semibold tracking-[-0.03em] text-fg">Launchpad</h1>
					{#if version}
						<span class="border border-edge bg-surface-1 px-2 py-0.5 font-mono text-[12px] text-fg-faint">v{version}</span>
					{/if}
				</div>
				<div class="flex items-center gap-3">
					<a
						href="/agents/new"
						class="flex items-center gap-2 rounded-[2px] bg-accent-primary px-5 py-2 text-[13px] font-medium text-surface-0 transition-[background-color] duration-150 hover:bg-accent-primary-hover"
					>
						<Plus size={14} />
						New Agent
					</a>
					<a
						href="/flows/new"
						class="flex items-center gap-2 rounded-[2px] border border-edge bg-transparent px-5 py-2 text-[13px] font-medium text-fg-muted transition-[color,border-color] duration-150 hover:border-accent-primary-dim hover:text-fg"
					>
						<Workflow size={14} />
						New Flow
					</a>
					<a
						href="/teams/new"
						class="flex items-center gap-2 rounded-[2px] border border-edge bg-transparent px-5 py-2 text-[13px] font-medium text-fg-muted transition-[color,border-color] duration-150 hover:border-accent-primary-dim hover:text-fg"
					>
						<Users size={14} />
						New Team
					</a>
					<a
						href="/system"
						class="flex items-center gap-2 rounded-[2px] border border-edge bg-transparent px-5 py-2 text-[13px] font-medium text-fg-muted transition-[color,border-color] duration-150 hover:border-accent-primary-dim hover:text-fg"
					>
						<Stethoscope size={14} />
						Run Doctor
					</a>
				</div>
			</div>

			<!-- Metrics strip -->
			{#if stats}
				<div class="flex border border-edge bg-surface-1 lg:col-span-3 animate-fade-in-up">
					<!-- Total Runs -->
					<div class="flex-1 px-5 py-4">
						<div class="metric-label">Total runs</div>
						<div class="metric-value mt-1">{stats.total_runs.toLocaleString()}</div>
						{#if recentAudit.length > 0}
							<div class="mt-1 font-mono text-[11px] text-fg-faint">
								<span class="text-accent-primary-dim">{recentSuccessCount}</span>/{recentAudit.length} recent ok
							</div>
						{/if}
					</div>
					<!-- Success Rate -->
					<div class="flex-1 border-l border-edge-subtle px-5 py-4">
						<div class="metric-label">Success rate</div>
						<div class="metric-value mt-1">{stats.success_rate}%</div>
						{#if recentSuccessRate !== null && successDiverging !== 'none'}
							<div class="mt-1 flex items-center gap-1 font-mono text-[11px]">
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
					<!-- Tokens / Run -->
					<div class="flex-1 border-l border-edge-subtle px-5 py-4">
						<div class="metric-label">Tokens / run</div>
						<div class="metric-value mt-1">~{formatTokens(tokensPerRun)}</div>
					</div>
					<!-- Avg Duration -->
					<div class="flex-1 border-l border-edge-subtle px-5 py-4">
						<div class="metric-label">Avg duration</div>
						<div class="metric-value mt-1">{formatDuration(stats.avg_duration_ms)}</div>
					</div>
				</div>
			{/if}

			<!-- Failing agents -->
			{#if errorAgents.length > 0}
				<div class="lg:col-span-3">
					<h2 class="section-label mb-3 flex items-center gap-2 text-fail">
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
			<div class="flex flex-col gap-6 lg:col-span-3 lg:flex-row lg:items-start">
				<!-- Left column: Fleet + Orchestration -->
				<div class="min-w-0 lg:flex-[2]">
				{#if stats && stats.top_agents.length > 0}
						<div class="mb-3 flex items-baseline justify-between">
							<h2 class="section-label">Agent Fleet</h2>
							<a href="/agents" class="text-[12px] text-fg-faint transition-[color] duration-150 hover:text-fg-muted">View all</a>
						</div>
						<div class="space-y-1.5">
							{#each stats.top_agents as topAgent, i}
								{@const agent = agentByName.get(topAgent.name)}
								{@const agentId = agentIdByName.get(topAgent.name)}
								{@const hasError = agent?.error != null}
								<a
									href={agentId ? `/agents/${agentId}` : '/agents'}
									class="group relative block overflow-hidden bg-surface-1 px-4 py-3 transition-[background-color,border-color] duration-200 hover:bg-surface-2
										{hasError ? 'card-surface-error' : 'card-surface'}
										animate-fade-in-up"
									style="animation-delay: {i * 40}ms"
								>
									<div class="relative flex items-center gap-3">
										<div class="w-[14px] shrink-0">
											{#if agent}
												<CapabilityGlyph features={agent.features} />
											{/if}
										</div>
										<span class="font-mono text-[13px] text-fg-muted transition-[color] duration-150 group-hover:text-fg">{topAgent.name}</span>
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

				<!-- Orchestration -->
				{#if flows.length > 0 || teams.length > 0}
					<div class="mt-6 border border-edge bg-surface-1 p-4">
						<h2 class="section-label mb-4">Orchestration</h2>
						<div class="space-y-5">
							{#if flows.length > 0}
								<div>
									<div class="mb-2 flex items-baseline justify-between">
										<h3 class="section-label text-accent-secondary">Flows</h3>
										<a href="/flows" class="text-[12px] text-fg-faint transition-[color] duration-150 hover:text-fg-muted">View all</a>
									</div>
									<div class="space-y-1.5">
										{#each flows.slice(0, 2) as flow, i}
											<a
												href="/flows/{flow.id}"
												class="card-surface flex items-center justify-between bg-surface-2 px-4 py-3 transition-[border-color,background-color] duration-150 hover:bg-surface-3 animate-fade-in-up"
												style="animation-delay: {i * 40}ms"
											>
												<div class="flex items-center gap-2.5">
													<Workflow size={14} class="shrink-0 text-accent-secondary" />
													<span class="font-mono text-[13px] text-fg-muted">{flow.name}</span>
												</div>
												<span class="rounded-full border border-accent-secondary/20 bg-accent-secondary/10 px-2 py-0.5 font-mono text-[10px] text-accent-secondary">{flow.agent_count} agents</span>
											</a>
										{/each}
									</div>
								</div>
							{/if}
							{#if teams.length > 0}
								<div>
									<div class="mb-2 flex items-baseline justify-between">
										<h3 class="section-label text-accent-secondary">Teams</h3>
										<a href="/teams" class="text-[12px] text-fg-faint transition-[color] duration-150 hover:text-fg-muted">View all</a>
									</div>
									<div class="space-y-1.5">
										{#each teams.slice(0, 2) as team, i}
											<a
												href="/teams/{team.id}"
												class="card-surface flex items-center justify-between bg-surface-2 px-4 py-3 transition-[border-color,background-color] duration-150 hover:bg-surface-3 animate-fade-in-up"
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

				<!-- MCP Health -->
				{#if mcpHealth && mcpHealth.total > 0}
					<div class="mt-6 border border-edge bg-surface-1 p-4">
						<div class="mb-3 flex items-baseline justify-between">
							<h2 class="section-label">MCP Servers</h2>
							<a href="/mcp" class="text-[12px] text-fg-faint transition-[color] duration-150 hover:text-fg-muted">View all</a>
						</div>
						<div class="flex items-center gap-4">
							<div class="flex items-center gap-2">
								<span class="status-dot" style="background: var(--color-ok)"></span>
								<span class="font-mono text-[13px] text-fg-muted">{mcpHealth.healthy} healthy</span>
							</div>
							{#if mcpHealth.unhealthy > 0}
								<div class="flex items-center gap-2">
									<span class="status-dot" style="background: var(--color-fail)"></span>
									<span class="font-mono text-[13px] text-fg-muted">{mcpHealth.unhealthy} unhealthy</span>
								</div>
							{/if}
							{#if mcpHealth.total - mcpHealth.healthy - mcpHealth.unhealthy > 0}
								<div class="flex items-center gap-2">
									<span class="status-dot" style="background: var(--color-fg-faint)"></span>
									<span class="font-mono text-[13px] text-fg-muted">{mcpHealth.total - mcpHealth.healthy - mcpHealth.unhealthy} unchecked</span>
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
							<h2 class="section-label">Recent Runs</h2>
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
											class="status-dot"
											class:bg-ok={!group.hasFailure}
											class:bg-fail={group.hasFailure}
										></span>
										<span class="font-mono text-[13px] text-fg-muted transition-[color] duration-150 group-hover:text-fg">{group.agentName}</span>
										{#if !isSingle}
											<span class="rounded-full border border-edge bg-surface-2 px-1.5 py-0.5 text-[10px] text-fg-faint">x{group.runs.length}</span>
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
