<script lang="ts">
	import type { DelegateEvent } from '$lib/api/types';
	import { Skeleton } from '$lib/components/ui/skeleton';

	let {
		events,
		agentNames,
		loading
	}: {
		events: DelegateEvent[];
		agentNames: string[];
		loading: boolean;
	} = $props();

	let filterSource = $state('');
	let filterTarget = $state('');
	let filterStatus = $state('');

	const filtered = $derived(() => {
		let result = events;
		if (filterSource) result = result.filter((e) => e.source_agent === filterSource);
		if (filterTarget) result = result.filter((e) => e.target_agent === filterTarget);
		if (filterStatus) result = result.filter((e) => e.status === filterStatus);
		return result;
	});

	function statusColor(status: string): string {
		switch (status) {
			case 'delivered': return 'bg-status-ok';
			case 'dropped':
			case 'error': return 'bg-status-fail';
			case 'filtered':
			case 'policy_denied': return 'bg-status-warn';
			case 'circuit_open': return 'bg-status-fail';
			default: return 'bg-fg-faint';
		}
	}

	function statusGlow(status: string): string {
		switch (status) {
			case 'delivered': return 'oklch(0.72 0.17 142)';
			case 'dropped':
			case 'error':
			case 'circuit_open': return 'oklch(0.65 0.20 25)';
			case 'filtered':
			case 'policy_denied': return 'oklch(0.80 0.18 85)';
			default: return 'transparent';
		}
	}

	function timeAgo(ts: string): string {
		const diff = Date.now() - new Date(ts).getTime();
		const mins = Math.floor(diff / 60000);
		if (mins < 1) return 'just now';
		if (mins < 60) return `${mins}m ago`;
		const hours = Math.floor(mins / 60);
		if (hours < 24) return `${hours}h ago`;
		const days = Math.floor(hours / 24);
		return `${days}d ago`;
	}
</script>

<div class="space-y-3">
	<div class="flex items-center justify-between">
		<h3 class="text-[12px] font-medium uppercase tracking-wide text-fg-faint">Delegation Events</h3>
		{#if !loading}
			<span class="border border-edge bg-surface-1 px-2 py-0.5 font-mono text-[11px] text-fg-faint">{filtered().length}</span>
		{/if}
	</div>

	<!-- Filters -->
	<div class="flex flex-wrap gap-2">
		<select
			bind:value={filterSource}
			class="border border-edge bg-surface-1 px-2 py-1 font-mono text-[11px] text-fg outline-none"
		>
			<option value="">All sources</option>
			{#each agentNames as name}
				<option value={name}>{name}</option>
			{/each}
		</select>
		<select
			bind:value={filterTarget}
			class="border border-edge bg-surface-1 px-2 py-1 font-mono text-[11px] text-fg outline-none"
		>
			<option value="">All targets</option>
			{#each agentNames as name}
				<option value={name}>{name}</option>
			{/each}
		</select>
		<select
			bind:value={filterStatus}
			class="border border-edge bg-surface-1 px-2 py-1 font-mono text-[11px] text-fg outline-none"
		>
			<option value="">All statuses</option>
			<option value="delivered">Delivered</option>
			<option value="dropped">Dropped</option>
			<option value="filtered">Filtered</option>
			<option value="error">Error</option>
			<option value="policy_denied">Policy denied</option>
			<option value="circuit_open">Circuit open</option>
		</select>
	</div>

	{#if loading}
		<Skeleton class="h-40 bg-surface-1" />
	{:else}
		{@const results = filtered()}
		{#if results.length === 0}
			<div class="py-12 text-center">
				<p class="text-[13px] text-fg-faint">No delegation events yet.</p>
				<p class="mt-1 text-[12px] text-fg-faint/60">Run this flow with <code class="font-mono">initrunner flow up</code> to see routing activity.</p>
			</div>
		{:else}
			<div class="border border-edge">
				<table class="w-full text-[12px]">
					<thead>
						<tr class="border-b border-edge bg-surface-1 text-left text-fg-faint">
							<th class="px-3 py-2 font-medium">Status</th>
							<th class="px-3 py-2 font-medium">Source</th>
							<th class="px-3 py-2 font-medium">Target</th>
							<th class="px-3 py-2 font-medium">Routing</th>
							<th class="px-3 py-2 font-medium">Time</th>
							<th class="px-3 py-2 font-medium">Run ID</th>
						</tr>
					</thead>
					<tbody>
						{#each results as event}
							<tr class="border-b border-edge/50 transition-[background-color] duration-100 hover:bg-surface-1/50">
								<td class="px-3 py-2">
									<span class="inline-flex items-center gap-1.5">
										<span
											class="h-2 w-2 rounded-full {statusColor(event.status)}"
											style="box-shadow: 0 0 4px {statusGlow(event.status)}"
										></span>
										<span class="font-mono text-fg-muted">{event.status}</span>
									</span>
								</td>
								<td class="px-3 py-2 font-mono text-fg-muted">{event.source_agent}</td>
								<td class="px-3 py-2 font-mono text-fg-muted">{event.target_agent}</td>
								<td class="px-3 py-2">
									{#if event.reason}
										{@const isLlm = event.reason.includes('llm')}
										<span class="font-mono text-[11px] {isLlm ? 'text-accent-secondary' : 'text-accent-primary'}">
											{event.reason}
										</span>
									{:else}
										<span class="text-fg-faint/40">--</span>
									{/if}
								</td>
								<td class="px-3 py-2 text-fg-faint" title={event.timestamp}>{timeAgo(event.timestamp)}</td>
								<td class="px-3 py-2 font-mono text-fg-faint">{event.source_run_id.substring(0, 8)}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		{/if}
	{/if}
</div>
