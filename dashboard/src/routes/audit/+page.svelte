<script lang="ts">
	import { onMount } from 'svelte';
	import { queryAudit } from '$lib/api/audit';
	import { fetchAuditStats } from '$lib/api/system';
	import type { AuditRecord, AuditStats } from '$lib/api/types';
	import { Skeleton } from '$lib/components/ui/skeleton';
	import AuditTable from '$lib/components/audit/AuditTable.svelte';
	import AuditDetailDrawer from '$lib/components/audit/AuditDetailDrawer.svelte';
	import { RefreshCw, Download, Activity, CheckCircle, Coins, Timer } from 'lucide-svelte';
	import { toast } from '$lib/stores/toast.svelte';

	let records = $state<AuditRecord[]>([]);
	let stats = $state<AuditStats | null>(null);
	let loading = $state(true);
	let agentFilter = $state('');
	let triggerFilter = $state('');
	let sinceFilter = $state('');
	let untilFilter = $state('');
	let showFailuresOnly = $state(false);
	let selectedRecord = $state<AuditRecord | null>(null);

	const filteredRecords = $derived(
		showFailuresOnly ? records.filter((r) => !r.success) : records
	);

	async function load() {
		loading = true;
		try {
			const params: Record<string, string | number | undefined> = {
				agent_name: agentFilter || undefined,
				trigger_type: triggerFilter || undefined,
				since: sinceFilter || undefined,
				until: untilFilter || undefined,
				limit: 200
			};
			const [r, s] = await Promise.all([
				queryAudit(params),
				fetchAuditStats({
					agent_name: agentFilter || undefined,
					since: sinceFilter || undefined,
					until: untilFilter || undefined
				})
			]);
			records = r;
			stats = s;
		} catch {
			toast.error('Failed to load audit data');
		} finally {
			loading = false;
		}
	}

	function exportRecords(format: 'json' | 'csv') {
		const data = filteredRecords;
		let content: string;
		let mime: string;
		let ext: string;

		if (format === 'json') {
			content = JSON.stringify(data, null, 2);
			mime = 'application/json';
			ext = 'json';
		} else {
			const cols = ['run_id', 'agent_name', 'timestamp', 'user_prompt', 'model', 'provider', 'tokens_in', 'tokens_out', 'total_tokens', 'duration_ms', 'success', 'error', 'trigger_type'] as const;
			const header = cols.join(',');
			const rows = data.map((r) =>
				cols.map((c) => {
					const val = r[c];
					if (val === null || val === undefined) return '';
					if (typeof val === 'string') return `"${val.replace(/"/g, '""')}"`;
					return String(val);
				}).join(',')
			);
			content = [header, ...rows].join('\n');
			mime = 'text/csv';
			ext = 'csv';
		}

		const blob = new Blob([content], { type: mime });
		const url = URL.createObjectURL(blob);
		const a = document.createElement('a');
		a.href = url;
		a.download = `audit-export.${ext}`;
		a.click();
		URL.revokeObjectURL(url);
	}

	onMount(load);
</script>

<div class="space-y-5">
	<!-- Header -->
	<div class="flex items-center gap-3">
		<h1 class="text-xl font-semibold tracking-[-0.02em] text-fg">Audit</h1>
		{#if !loading}
			<span class="border border-edge bg-surface-1 px-2 py-0.5 font-mono text-[12px] text-fg-faint">
				{filteredRecords.length}
			</span>
		{/if}
	</div>

	<!-- Stats strip -->
	{#if stats && !loading}
		<div class="grid grid-cols-2 gap-2 lg:grid-cols-4">
			<div class="card-surface flex items-center gap-2.5 bg-surface-1 px-3 py-2 animate-fade-in-up" style="animation-delay: 0ms">
				<Activity size={14} class="shrink-0 text-accent-primary/60" />
				<div>
					<div class="font-mono text-[18px] font-semibold tracking-[-0.02em] text-fg" style="font-variant-numeric: tabular-nums">{stats.total_runs.toLocaleString()}</div>
					<div class="text-[12px] text-fg-faint">runs</div>
				</div>
			</div>
			<div class="card-surface flex items-center gap-2.5 bg-surface-1 px-3 py-2 animate-fade-in-up" style="animation-delay: 60ms">
				<CheckCircle size={14} class="shrink-0 {stats.success_rate >= 90 ? 'text-ok' : stats.success_rate >= 70 ? 'text-warn' : 'text-fail'}" />
				<div>
					<div class="font-mono text-[18px] font-semibold tracking-[-0.02em] text-fg" style="font-variant-numeric: tabular-nums">{stats.success_rate}%</div>
					<div class="text-[12px] text-fg-faint">success</div>
				</div>
			</div>
			<div class="card-surface flex items-center gap-2.5 bg-surface-1 px-3 py-2 animate-fade-in-up" style="animation-delay: 120ms">
				<Coins size={14} class="shrink-0 text-accent-primary/60" />
				<div>
					<div class="font-mono text-[18px] font-semibold tracking-[-0.02em] text-fg" style="font-variant-numeric: tabular-nums">{stats.total_tokens.toLocaleString()}</div>
					<div class="text-[12px] text-fg-faint">tokens</div>
				</div>
			</div>
			<div class="card-surface flex items-center gap-2.5 bg-surface-1 px-3 py-2 animate-fade-in-up" style="animation-delay: 180ms">
				<Timer size={14} class="shrink-0 text-accent-primary/60" />
				<div>
					<div class="font-mono text-[18px] font-semibold tracking-[-0.02em] text-fg" style="font-variant-numeric: tabular-nums">{stats.avg_duration_ms.toLocaleString()}ms</div>
					<div class="text-[12px] text-fg-faint">avg duration</div>
				</div>
			</div>
		</div>
	{/if}

	<!-- Filter bar -->
	<div class="flex flex-wrap items-center gap-3">
		<input
			bind:value={agentFilter}
			placeholder="Filter by agent..."
			class="max-w-[180px] border border-edge bg-surface-1 px-3 py-1.5 font-mono text-[13px] text-fg outline-none transition-[border-color,box-shadow] duration-150 placeholder:text-fg-faint focus:border-accent-primary/40 focus:shadow-[0_0_0_3px_oklch(0.91_0.20_128/0.08)]"
			onkeydown={(e) => e.key === 'Enter' && load()}
		/>

		<input
			bind:value={triggerFilter}
			placeholder="Trigger type..."
			class="max-w-[140px] border border-edge bg-surface-1 px-3 py-1.5 font-mono text-[13px] text-fg outline-none transition-[border-color,box-shadow] duration-150 placeholder:text-fg-faint focus:border-accent-primary/40 focus:shadow-[0_0_0_3px_oklch(0.91_0.20_128/0.08)]"
			onkeydown={(e) => e.key === 'Enter' && load()}
		/>

		<!-- Date range -->
		<div class="flex items-center gap-1.5">
			<input
				type="date"
				bind:value={sinceFilter}
				class="border border-edge bg-surface-1 px-2 py-1.5 font-mono text-[13px] text-fg-muted outline-none transition-[border-color,box-shadow] duration-150 focus:border-accent-primary/40"
				onchange={load}
			/>
			<span class="text-[13px] text-fg-faint">to</span>
			<input
				type="date"
				bind:value={untilFilter}
				class="border border-edge bg-surface-1 px-2 py-1.5 font-mono text-[13px] text-fg-muted outline-none transition-[border-color,box-shadow] duration-150 focus:border-accent-primary/40"
				onchange={load}
			/>
		</div>

		<!-- Success filter -->
		<div class="flex items-center gap-0.5 rounded-full border border-edge bg-surface-1 p-0.5">
			<button
				class="rounded-full px-2.5 py-1 text-[13px] font-medium transition-[color,background-color] duration-150"
				class:bg-surface-2={!showFailuresOnly}
				class:text-fg={!showFailuresOnly}
				class:text-fg-faint={showFailuresOnly}
				onclick={() => (showFailuresOnly = false)}
			>
				All
			</button>
			<button
				class="rounded-full px-2.5 py-1 text-[13px] font-medium transition-[color,background-color] duration-150"
				class:bg-surface-2={showFailuresOnly}
				class:text-fg={showFailuresOnly}
				class:text-fg-faint={!showFailuresOnly}
				onclick={() => (showFailuresOnly = true)}
			>
				Failures
			</button>
		</div>

		<div class="ml-auto flex items-center gap-2">
			<!-- Export -->
			<div class="flex items-center gap-0.5 border border-edge bg-surface-1 p-0.5">
				<button
					class="flex items-center gap-1 px-2 py-1 text-[13px] text-fg-faint transition-[color,background-color] duration-150 hover:bg-surface-2 hover:text-fg-muted"
					onclick={() => exportRecords('json')}
				>
					<Download size={11} />
					JSON
				</button>
				<button
					class="flex items-center gap-1 px-2 py-1 text-[13px] text-fg-faint transition-[color,background-color] duration-150 hover:bg-surface-2 hover:text-fg-muted"
					onclick={() => exportRecords('csv')}
				>
					<Download size={11} />
					CSV
				</button>
			</div>

			<button
				class="flex items-center gap-1.5 rounded-full border border-edge px-3 py-1.5 text-[13px] text-fg-faint transition-[color,background-color,border-color] duration-150 hover:bg-surface-2 hover:text-fg-muted hover:border-accent-primary/20"
				onclick={load}
				aria-label="Refresh"
			>
				<RefreshCw size={12} />
				Refresh
			</button>
		</div>
	</div>

	<!-- Table -->
	{#if loading}
		<Skeleton class="h-64 bg-surface-1" />
	{:else}
		<div class="overflow-hidden border border-edge">
			<AuditTable records={filteredRecords} onRowClick={(r) => (selectedRecord = r)} />
		</div>
	{/if}
</div>

<!-- Detail drawer -->
{#if selectedRecord}
	<AuditDetailDrawer record={selectedRecord} onClose={() => (selectedRecord = null)} />
{/if}
