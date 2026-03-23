<script lang="ts">
	import { onMount } from 'svelte';
	import { listAgents } from '$lib/api/agents';
	import { queryAudit } from '$lib/api/audit';
	import { fetchAuditStats } from '$lib/api/system';
	import { request } from '$lib/api/client';
	import type { AgentSummary, AuditRecord, AuditStats, HealthStatus } from '$lib/api/types';
	import { Skeleton } from '$lib/components/ui/skeleton';
	import { Plus, Stethoscope, Activity, CheckCircle, Coins, Timer, AlertTriangle } from 'lucide-svelte';

	let agents = $state<AgentSummary[]>([]);
	let recentAudit = $state<AuditRecord[]>([]);
	let stats = $state<AuditStats | null>(null);
	let version = $state('');
	let loading = $state(true);

	const errorAgents = $derived(agents.filter((a) => a.error));
	const hasAgents = $derived(agents.length > 0);

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
			const [a, audit, s, health] = await Promise.all([
				listAgents(),
				queryAudit({ limit: 10 }),
				fetchAuditStats(),
				request<HealthStatus>('/api/health')
			]);
			agents = a;
			recentAudit = audit;
			stats = s;
			version = health.version;
		} catch {
			// API not available
		} finally {
			loading = false;
		}
	});
</script>

<div class="space-y-8">
	{#if loading}
		<Skeleton class="h-6 w-48 rounded-sm bg-surface-1" />
		<Skeleton class="h-40 rounded-sm bg-surface-1" />
		<Skeleton class="h-64 rounded-sm bg-surface-1" />
	{:else if !hasAgents}
		<!-- Zero state: Welcome screen -->
		<div class="flex flex-col items-center justify-center py-20">
			<div class="mb-2 font-mono text-[11px] font-medium uppercase tracking-[0.08em] text-fg-faint">
				{#if version}v{version}{/if}
			</div>
			<h1 class="mb-3 text-2xl font-medium text-fg">Welcome to InitRunner</h1>
			<p class="mb-10 max-w-md text-center text-[14px] leading-relaxed text-fg-muted">
				Define AI agents as YAML, run them anywhere. Create your first agent to get started.
			</p>
			<div class="flex gap-4">
				<a
					href="/agents/new"
					class="flex items-center gap-2 rounded-sm bg-orange px-5 py-2.5 text-[13px] font-medium text-white transition-[background-color] duration-150 hover:bg-orange-hover"
				>
					<Plus size={16} />
					Create an Agent
				</a>
				<a
					href="/system"
					class="flex items-center gap-2 rounded-sm border border-edge bg-surface-1 px-5 py-2.5 text-[13px] font-medium text-fg-muted transition-[color,background-color] duration-150 hover:bg-surface-2 hover:text-fg"
				>
					<Stethoscope size={16} />
					Run Doctor
				</a>
			</div>
		</div>
	{:else}
		<!-- Header -->
		<div class="flex items-center gap-3">
			<h1 class="text-lg font-medium text-fg">Launchpad</h1>
			{#if version}
				<span class="rounded-sm border border-edge bg-surface-1 px-2 py-0.5 font-mono text-[11px] text-fg-faint">v{version}</span>
			{/if}
		</div>

		<!-- Stats strip -->
		{#if stats}
			<div class="grid grid-cols-2 gap-3 lg:grid-cols-4">
				<div class="flex items-center gap-3 rounded-sm border border-edge bg-surface-1 px-4 py-3">
					<Activity size={16} class="shrink-0 text-fg-faint" />
					<div>
						<div class="font-mono text-[18px] font-medium text-fg" style="font-variant-numeric: tabular-nums">{stats.total_runs.toLocaleString()}</div>
						<div class="text-[11px] text-fg-faint">total runs</div>
					</div>
				</div>
				<div class="flex items-center gap-3 rounded-sm border border-edge bg-surface-1 px-4 py-3">
					<CheckCircle size={16} class="shrink-0 {stats.success_rate >= 90 ? 'text-ok' : stats.success_rate >= 70 ? 'text-warn' : 'text-fail'}" />
					<div>
						<div class="font-mono text-[18px] font-medium text-fg" style="font-variant-numeric: tabular-nums">{stats.success_rate}%</div>
						<div class="text-[11px] text-fg-faint">success rate</div>
					</div>
				</div>
				<div class="flex items-center gap-3 rounded-sm border border-edge bg-surface-1 px-4 py-3">
					<Coins size={16} class="shrink-0 text-fg-faint" />
					<div>
						<div class="font-mono text-[18px] font-medium text-fg" style="font-variant-numeric: tabular-nums">{stats.total_tokens.toLocaleString()}</div>
						<div class="text-[11px] text-fg-faint">total tokens</div>
					</div>
				</div>
				<div class="flex items-center gap-3 rounded-sm border border-edge bg-surface-1 px-4 py-3">
					<Timer size={16} class="shrink-0 text-fg-faint" />
					<div>
						<div class="font-mono text-[18px] font-medium text-fg" style="font-variant-numeric: tabular-nums">{stats.avg_duration_ms.toLocaleString()}ms</div>
						<div class="text-[11px] text-fg-faint">avg duration</div>
					</div>
				</div>
			</div>
		{/if}

		<!-- Quick actions -->
		<div class="flex gap-3">
			<a
				href="/agents/new"
				class="flex items-center gap-2 rounded-sm bg-orange px-4 py-2 text-[13px] font-medium text-white transition-[background-color] duration-150 hover:bg-orange-hover"
			>
				<Plus size={14} />
				New Agent
			</a>
			<a
				href="/system"
				class="flex items-center gap-2 rounded-sm border border-edge bg-surface-1 px-4 py-2 text-[13px] font-medium text-fg-muted transition-[color,background-color] duration-150 hover:bg-surface-2 hover:text-fg"
			>
				<Stethoscope size={14} />
				Run Doctor
			</a>
		</div>

		<!-- Failing agents -->
		{#if errorAgents.length > 0}
			<div>
				<h2 class="mb-3 flex items-center gap-2 font-mono text-[11px] font-medium uppercase tracking-[0.08em] text-fail">
					<AlertTriangle size={12} />
					Failing Agents
				</h2>
				<div class="space-y-1">
					{#each errorAgents as agent}
						<a
							href="/agents/{agent.id}"
							class="flex items-baseline gap-3 rounded-sm border border-fail/20 bg-fail/5 px-3 py-2 transition-[background-color] duration-150 hover:bg-fail/10"
						>
							<span class="text-[13px] font-medium text-fg">{agent.name}</span>
							<span class="truncate font-mono text-xs text-fail">{agent.error}</span>
						</a>
					{/each}
				</div>
			</div>
		{/if}

		<!-- Top agents -->
		{#if stats && stats.top_agents.length > 0}
			<div>
				<h2 class="mb-3 font-mono text-[11px] font-medium uppercase tracking-[0.08em] text-fg-faint">Top Agents (by runs)</h2>
				<div class="space-y-1.5">
					{#each stats.top_agents as agent}
						{@const maxCount = stats.top_agents[0]?.count ?? 1}
						{@const pct = Math.round((agent.count / maxCount) * 100)}
						<div class="relative overflow-hidden rounded-sm border border-edge bg-surface-1 px-3 py-2">
							<div class="absolute inset-y-0 left-0 bg-orange/10" style="width: {pct}%"></div>
							<div class="relative flex items-baseline justify-between">
								<span class="font-mono text-[12px] text-fg-muted">{agent.name}</span>
								<span class="font-mono text-[11px] text-fg-faint">
									{agent.count} runs &middot; {agent.avg_duration_ms}ms avg
								</span>
							</div>
						</div>
					{/each}
				</div>
			</div>
		{/if}

		<!-- Recent activity -->
		{#if recentAudit.length > 0}
			<div>
				<div class="mb-3 flex items-baseline justify-between">
					<h2 class="font-mono text-[11px] font-medium uppercase tracking-[0.08em] text-fg-faint">Recent Activity</h2>
					<a href="/audit" class="text-[12px] text-fg-faint transition-[color] duration-150 hover:text-fg-muted">View all</a>
				</div>
				<div class="space-y-0.5">
					{#each recentAudit as run (run.run_id)}
						<div class="flex items-center gap-3 rounded-sm px-3 py-1.5 transition-[background-color] duration-150 hover:bg-surface-1">
							<span
								class="inline-block h-1.5 w-1.5 shrink-0 rounded-full"
								class:bg-ok={run.success}
								class:bg-fail={!run.success}
							></span>
							<span class="font-mono text-[12px] text-fg-muted">{run.agent_name}</span>
							<span class="hidden truncate text-[12px] text-fg-faint sm:inline">{truncate(run.user_prompt, 50)}</span>
							<span class="ml-auto shrink-0 font-mono text-[11px] text-fg-faint">{timeAgo(run.timestamp)}</span>
						</div>
					{/each}
				</div>
			</div>
		{:else}
			<div class="py-16 text-center text-[13px] text-fg-faint">
				No runs yet. Run an agent to see activity here.
			</div>
		{/if}
	{/if}
</div>
