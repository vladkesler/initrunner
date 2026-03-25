<script lang="ts">
	import { onMount } from 'svelte';
	import { listAgents } from '$lib/api/agents';
	import { queryAudit } from '$lib/api/audit';
	import { fetchAuditStats } from '$lib/api/system';
	import { request } from '$lib/api/client';
	import type { AgentSummary, AuditRecord, AuditStats, HealthStatus } from '$lib/api/types';
	import { Skeleton } from '$lib/components/ui/skeleton';
	import { Plus, BookOpen, Stethoscope, Activity, CheckCircle, Coins, Timer, AlertTriangle, ArrowUpRight, Workflow, Users, ExternalLink } from 'lucide-svelte';
	import { fetchComposeList } from '$lib/api/compose';
	import { fetchTeamList } from '$lib/api/teams';
	import { getBuilderOptions, getStarters, type BuilderOptions, type StarterInfo } from '$lib/api/builder';
	import type { ComposeSummary, TeamSummary } from '$lib/api/types';
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

	onMount(async () => {
		try {
			const [a, c, t, audit, s, health, opts, st] = await Promise.all([
				listAgents(),
				fetchComposeList().catch(() => [] as ComposeSummary[]),
				fetchTeamList().catch(() => [] as TeamSummary[]),
				queryAudit({ limit: 10 }),
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
			// API not available
		} finally {
			loading = false;
		}
	});

	async function reloadProviders() {
		try {
			builderOptions = await getBuilderOptions();
		} catch {
			// best effort
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
		<!-- Bento grid layout -->
		<div class="grid grid-cols-1 gap-4 lg:grid-cols-3">
			<!-- Header — full width with inline actions -->
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

			<!-- Stats strip — full width -->
			{#if stats}
				<div class="grid grid-cols-2 gap-3 lg:col-span-3 lg:grid-cols-4">
					<div class="card-surface flex items-center gap-3 bg-surface-1 px-4 py-3 animate-fade-in-up" style="animation-delay: 0ms">
						<Activity size={16} class="shrink-0 text-accent-primary/60" />
						<div>
							<div class="font-mono text-[22px] font-semibold tracking-[-0.02em] text-fg" style="font-variant-numeric: tabular-nums">{stats.total_runs.toLocaleString()}</div>
							<div class="text-[12px] text-fg-faint">total runs</div>
						</div>
					</div>
					<div class="card-surface flex items-center gap-3 bg-surface-1 px-4 py-3 animate-fade-in-up" style="animation-delay: 60ms">
						<CheckCircle size={16} class="shrink-0 {stats.success_rate >= 90 ? 'text-ok' : stats.success_rate >= 70 ? 'text-warn' : 'text-fail'}" />
						<div>
							<div class="font-mono text-[22px] font-semibold tracking-[-0.02em] text-fg" style="font-variant-numeric: tabular-nums">{stats.success_rate}%</div>
							<div class="text-[12px] text-fg-faint">success rate</div>
						</div>
					</div>
					<div class="card-surface flex items-center gap-3 bg-surface-1 px-4 py-3 animate-fade-in-up" style="animation-delay: 120ms">
						<Coins size={16} class="shrink-0 text-accent-primary/60" />
						<div>
							<div class="font-mono text-[22px] font-semibold tracking-[-0.02em] text-fg" style="font-variant-numeric: tabular-nums">{stats.total_tokens.toLocaleString()}</div>
							<div class="text-[12px] text-fg-faint">total tokens</div>
						</div>
					</div>
					<div class="card-surface flex items-center gap-3 bg-surface-1 px-4 py-3 animate-fade-in-up" style="animation-delay: 180ms">
						<Timer size={16} class="shrink-0 text-accent-primary/60" />
						<div>
							<div class="font-mono text-[22px] font-semibold tracking-[-0.02em] text-fg" style="font-variant-numeric: tabular-nums">{stats.avg_duration_ms.toLocaleString()}ms</div>
							<div class="text-[12px] text-fg-faint">avg duration</div>
						</div>
					</div>
				</div>
			{/if}

			<!-- Failing agents — full width -->
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
								class="flex items-baseline gap-3 border border-fail/20 bg-fail/5 px-3 py-2 transition-[background-color] duration-150 hover:bg-fail/10"
							>
								<span class="text-[13px] font-medium text-fg">{agent.name}</span>
								<span class="truncate font-mono text-sm text-fail">{agent.error}</span>
							</a>
						{/each}
					</div>
				</div>
			{/if}

			<!-- Top agents — 2 cols -->
			{#if stats && stats.top_agents.length > 0}
				<div class="lg:col-span-2">
					<div class="mb-3 flex items-baseline justify-between">
						<h2 class="font-mono text-[12px] font-medium uppercase tracking-[0.1em] text-fg-faint">Top Agents (by runs)</h2>
						<a href="/agents" class="text-[12px] text-fg-faint transition-[color] duration-150 hover:text-fg-muted">View all</a>
					</div>
					<div class="space-y-1.5">
						{#each stats.top_agents as agent}
							{@const maxCount = stats.top_agents[0]?.count ?? 1}
							{@const pct = Math.round((agent.count / maxCount) * 100)}
							{@const agentId = agentIdByName.get(agent.name)}
							<a
								href={agentId ? `/agents/${agentId}` : '/agents'}
								class="group card-surface relative block overflow-hidden bg-surface-1 px-3 py-2 transition-[background-color] duration-150 hover:bg-surface-2"
							>
								<div class="absolute inset-y-0 left-0 bg-accent-primary/15" style="width: {pct}%"></div>
								<div class="relative flex items-center justify-between">
									<span class="font-mono text-[13px] text-fg-muted transition-[color] duration-150 group-hover:text-accent-primary">{agent.name}</span>
									<div class="flex items-center gap-2">
										<span class="font-mono text-[13px] text-fg-faint">
											{agent.count} runs &middot; {agent.avg_duration_ms}ms avg
										</span>
										<ArrowUpRight size={12} class="shrink-0 text-fg-faint opacity-0 transition-opacity duration-150 group-hover:opacity-100" />
									</div>
								</div>
							</a>
						{/each}
					</div>
				</div>
			{/if}

			<!-- Recent activity — 1 col -->
			{#if recentAudit.length > 0}
				<div class="lg:col-span-1">
					<div class="mb-3 flex items-baseline justify-between">
						<h2 class="font-mono text-[12px] font-medium uppercase tracking-[0.1em] text-fg-faint">Recent Activity</h2>
						<a href="/audit" class="text-[12px] text-fg-faint transition-[color] duration-150 hover:text-fg-muted">View all</a>
					</div>
					<div class="space-y-0.5">
						{#each recentAudit as run (run.run_id)}
							{@const agentId = agentIdByName.get(run.agent_name)}
							<a
								href={agentId ? `/agents/${agentId}` : '/agents'}
								class="group flex items-center gap-3 px-3 py-1.5 transition-[background-color] duration-150 hover:bg-surface-1"
							>
								<span
									class="inline-block h-1.5 w-1.5 shrink-0 rounded-full"
									class:bg-ok={run.success}
									class:bg-fail={!run.success}
									style="box-shadow: 0 0 4px {run.success ? 'var(--color-ok)' : 'var(--color-fail)'}"
								></span>
								<span class="font-mono text-[13px] text-fg-muted transition-[color] duration-150 group-hover:text-accent-primary">{run.agent_name}</span>
								<span class="ml-auto shrink-0 font-mono text-[12px] text-fg-faint">{timeAgo(run.timestamp)}</span>
							</a>
						{/each}
					</div>
				</div>
			{:else}
				<div class="py-16 text-center text-[13px] text-fg-faint lg:col-span-1">
					No runs yet. Run an agent to see activity here.
				</div>
			{/if}

			<!-- Orchestration -->
			{#if composes.length > 0 || teams.length > 0}
				<h2 class="font-mono text-[12px] font-medium uppercase tracking-[0.1em] text-fg-faint lg:col-span-3">
					Orchestration
				</h2>
			{/if}

			<!-- Compositions card -->
			{#if composes.length > 0}
				<div class="lg:col-span-1">
					<div class="mb-3 flex items-baseline justify-between">
						<h2 class="font-mono text-[12px] font-medium uppercase tracking-[0.1em] text-fg-faint">Compositions</h2>
						<a href="/compose" class="text-[12px] text-fg-faint transition-[color] duration-150 hover:text-fg-muted">View all</a>
					</div>
					<div class="space-y-1">
						{#each composes.slice(0, 3) as compose}
							<a
								href="/compose/{compose.id}"
								class="flex items-center justify-between border border-edge bg-surface-1 px-3 py-2 transition-[border-color,background-color] duration-150 hover:border-accent-primary/20"
							>
								<div class="flex items-center gap-2">
									<Workflow size={12} class="text-fg-faint" />
									<span class="font-mono text-[12px] text-fg-muted">{compose.name}</span>
								</div>
								<span class="font-mono text-[11px] text-fg-faint">{compose.service_count} svc</span>
							</a>
						{/each}
					</div>
				</div>
			{/if}

			<!-- Teams card -->
			{#if teams.length > 0}
				<div class="lg:col-span-1">
					<div class="mb-3 flex items-baseline justify-between">
						<h2 class="font-mono text-[12px] font-medium uppercase tracking-[0.1em] text-fg-faint">Teams</h2>
						<a href="/teams" class="text-[12px] text-fg-faint transition-[color] duration-150 hover:text-fg-muted">View all</a>
					</div>
					<div class="space-y-1">
						{#each teams.slice(0, 3) as team}
							<a
								href="/teams/{team.id}"
								class="flex items-center justify-between border border-edge bg-surface-1 px-3 py-2 transition-[border-color,background-color] duration-150 hover:border-accent-primary/20"
							>
								<div class="flex items-center gap-2">
									<Users size={12} class="text-fg-faint" />
									<span class="font-mono text-[12px] text-fg-muted">{team.name}</span>
								</div>
								<div class="flex items-center gap-2">
									<span class="rounded-full border border-edge bg-surface-2 px-1.5 py-0.5 font-mono text-[10px] text-fg-faint">{team.strategy}</span>
									<span class="font-mono text-[11px] text-fg-faint">{team.persona_count} personas</span>
								</div>
							</a>
						{/each}
					</div>
				</div>
			{/if}
		</div>
	{/if}
</div>
