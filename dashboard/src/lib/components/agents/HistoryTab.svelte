<script lang="ts">
	import { onMount } from 'svelte';
	import { queryAudit } from '$lib/api/audit';
	import type { AuditRecord } from '$lib/api/types';
	import { Skeleton } from '$lib/components/ui/skeleton';
	import AuditTable from '$lib/components/audit/AuditTable.svelte';
	import AuditDetailDrawer from '$lib/components/audit/AuditDetailDrawer.svelte';
	import { RefreshCw } from 'lucide-svelte';

	let { agentName, refreshKey = 0 }: { agentName: string; refreshKey?: number } = $props();

	let records = $state<AuditRecord[]>([]);
	let loading = $state(true);
	let triggerFilter = $state('');
	let sinceFilter = $state('');
	let untilFilter = $state('');
	let showFailuresOnly = $state(false);
	let selectedRecord = $state<AuditRecord | null>(null);
	let mounted = $state(false);

	const filteredRecords = $derived(
		showFailuresOnly ? records.filter((r) => !r.success) : records
	);

	async function load() {
		loading = true;
		try {
			records = await queryAudit({
				agent_name: agentName,
				trigger_type: triggerFilter || undefined,
				since: sinceFilter || undefined,
				until: untilFilter || undefined,
				limit: 200
			});
		} catch {
			// API not available
		} finally {
			loading = false;
		}
	}

	onMount(() => {
		load();
		mounted = true;
	});

	// Auto-refresh when refreshKey changes (after a run completes)
	$effect(() => {
		// Read refreshKey to establish dependency
		const _key = refreshKey;
		if (mounted && _key > 0) {
			load();
		}
	});
</script>

<div class="space-y-4">
	<!-- Filter bar -->
	<div class="flex flex-wrap items-center gap-3">
		<input
			bind:value={triggerFilter}
			placeholder="Trigger type..."
			class="max-w-[140px] border border-edge bg-surface-1 px-3 py-1.5 font-mono text-[13px] text-fg outline-none transition-[border-color,box-shadow] duration-150 placeholder:text-fg-faint focus:border-accent-primary/40 focus:shadow-[0_0_0_3px_oklch(0.91_0.20_128/0.08)]"
			onkeydown={(e) => e.key === 'Enter' && load()}
		/>

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

		<button
			class="ml-auto flex items-center gap-1.5 rounded-full border border-edge px-3 py-1.5 text-[13px] text-fg-faint transition-[color,background-color,border-color] duration-150 hover:border-accent-primary/20 hover:bg-surface-2 hover:text-fg-muted"
			onclick={load}
			aria-label="Refresh"
		>
			<RefreshCw size={12} />
			Refresh
		</button>
	</div>

	<!-- Table -->
	{#if loading}
		<Skeleton class="h-64 bg-surface-1" />
	{:else}
		<div class="overflow-hidden border border-edge">
			<AuditTable records={filteredRecords} hideAgentColumn onRowClick={(r) => (selectedRecord = r)} />
		</div>
		{#if filteredRecords.length > 0}
			<p class="text-[12px] text-fg-faint">{filteredRecords.length} records</p>
		{/if}
	{/if}
</div>

{#if selectedRecord}
	<AuditDetailDrawer record={selectedRecord} onClose={() => (selectedRecord = null)} />
{/if}
