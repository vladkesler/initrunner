<script lang="ts">
	import { page } from '$app/state';
	import { onMount } from 'svelte';
	import { fetchComposeDetail, fetchComposeYaml, fetchComposeEvents } from '$lib/api/compose';
	import type { ComposeDetail, DelegateEvent } from '$lib/api/types';
	import { Skeleton } from '$lib/components/ui/skeleton';
	import { ArrowLeft, ChevronDown, Database, ExternalLink } from 'lucide-svelte';

	let detail: ComposeDetail | null = $state(null);
	let yaml = $state('');
	let events = $state<DelegateEvent[]>([]);
	let loading = $state(true);
	let eventsLoading = $state(true);
	let showYaml = $state(false);

	// Event filters
	let filterSource = $state('');
	let filterTarget = $state('');
	let filterStatus = $state('');

	const composeId = $derived(page.params.id ?? '');

	const filteredEvents = $derived(() => {
		let result = events;
		if (filterSource) result = result.filter((e) => e.source_service === filterSource);
		if (filterTarget) result = result.filter((e) => e.target_service === filterTarget);
		if (filterStatus) result = result.filter((e) => e.status === filterStatus);
		return result;
	});

	const serviceNames = $derived(detail ? detail.services.map((s) => s.name) : []);

	function statusColor(status: string): string {
		switch (status) {
			case 'delivered': return 'bg-status-ok';
			case 'dropped':
			case 'error': return 'bg-status-fail';
			case 'filtered': return 'bg-status-warn';
			default: return 'bg-fg-faint';
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

	onMount(async () => {
		try {
			const [d, y] = await Promise.all([
				fetchComposeDetail(composeId),
				fetchComposeYaml(composeId)
			]);
			detail = d;
			yaml = y.yaml;
		} catch {
			// not found
		} finally {
			loading = false;
		}

		try {
			events = await fetchComposeEvents(composeId);
		} catch {
			// no events
		} finally {
			eventsLoading = false;
		}
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
		<Skeleton class="h-64 bg-surface-1" />
	{:else if detail}
		<!-- Header -->
		<div>
			<div class="flex items-center gap-3">
				<h1 class="text-xl font-semibold tracking-[-0.02em] text-fg">{detail.name}</h1>
				<span class="border border-edge bg-surface-1 px-2 py-0.5 font-mono text-[12px] text-fg-faint">
					{detail.services.length} services
				</span>
			</div>
			{#if detail.description}
				<p class="mt-1 text-[13px] text-fg-muted">{detail.description}</p>
			{/if}
		</div>

		<!-- Split layout -->
		<div class="flex flex-1 flex-col gap-4 lg:flex-row">
			<!-- Left: Topology -->
			<div class="w-full shrink-0 space-y-3 lg:w-[340px]">
				<h3 class="text-[12px] font-medium uppercase tracking-wide text-fg-faint">Topology</h3>

				<div class="space-y-1.5">
					{#each detail.services as svc, idx}
						{#if idx > 0}
							<div class="ml-6 h-3 w-px bg-fg-faint/20"></div>
						{/if}
						<div class="border border-edge bg-surface-1 p-3">
							<div class="flex items-center justify-between">
								<span class="font-mono text-[13px] font-medium text-fg">{svc.name}</span>
								{#if svc.restart_condition !== 'none'}
									<span class="rounded-full border border-edge bg-surface-2 px-1.5 py-0.5 font-mono text-[10px] text-fg-faint">{svc.restart_condition}</span>
								{/if}
							</div>

							<!-- Role link -->
							<div class="mt-1 text-[12px] text-fg-faint">
								{#if svc.agent_id}
									<a
										href="/agents/{svc.agent_id}"
										class="inline-flex items-center gap-1 text-accent-primary transition-[color] duration-150 hover:text-accent-primary/80"
									>
										{svc.agent_name || svc.role_path}
										<ExternalLink size={10} />
									</a>
								{:else}
									<span class="font-mono">{svc.role_path}</span>
								{/if}
							</div>

							<!-- Sink -->
							{#if svc.sink_summary}
								<div class="mt-1 font-mono text-[11px] text-fg-faint/70">{svc.sink_summary}</div>
							{/if}

							<!-- Depends on -->
							{#if svc.depends_on.length > 0}
								<div class="mt-1 text-[11px] text-fg-faint/60">
									depends on: {svc.depends_on.join(', ')}
								</div>
							{/if}
						</div>
					{/each}
				</div>

				<!-- Shared resources -->
				{#if detail.shared_memory_enabled || detail.shared_documents_enabled}
					<div class="flex flex-wrap gap-2">
						{#if detail.shared_memory_enabled}
							<span class="flex items-center gap-1 rounded-full border border-edge bg-surface-1 px-2 py-0.5 font-mono text-[11px] text-fg-faint">
								<Database size={10} />
								Shared memory
							</span>
						{/if}
						{#if detail.shared_documents_enabled}
							<span class="flex items-center gap-1 rounded-full border border-edge bg-surface-1 px-2 py-0.5 font-mono text-[11px] text-fg-faint">
								<Database size={10} />
								Shared documents
							</span>
						{/if}
					</div>
				{/if}

				<!-- YAML viewer -->
				<button
					class="flex items-center gap-1.5 text-[12px] text-fg-faint transition-[color] duration-150 hover:text-fg-muted"
					onclick={() => (showYaml = !showYaml)}
				>
					<ChevronDown size={12} class="transition-transform duration-150 {showYaml ? 'rotate-0' : '-rotate-90'}" />
					YAML
				</button>
				{#if showYaml}
					<pre class="max-h-80 overflow-auto border border-edge bg-surface-2 p-3 font-mono text-[11px] text-fg-faint">{yaml}</pre>
				{/if}
			</div>

			<!-- Right: Events -->
			<div class="flex-1 space-y-3">
				<div class="flex items-center justify-between">
					<h3 class="text-[12px] font-medium uppercase tracking-wide text-fg-faint">Delegation Events</h3>
					{#if !eventsLoading}
						<span class="border border-edge bg-surface-1 px-2 py-0.5 font-mono text-[11px] text-fg-faint">{filteredEvents().length}</span>
					{/if}
				</div>

				<!-- Filters -->
				<div class="flex flex-wrap gap-2">
					<select
						bind:value={filterSource}
						class="border border-edge bg-surface-1 px-2 py-1 font-mono text-[11px] text-fg outline-none"
					>
						<option value="">All sources</option>
						{#each serviceNames as name}
							<option value={name}>{name}</option>
						{/each}
					</select>
					<select
						bind:value={filterTarget}
						class="border border-edge bg-surface-1 px-2 py-1 font-mono text-[11px] text-fg outline-none"
					>
						<option value="">All targets</option>
						{#each serviceNames as name}
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
					</select>
				</div>

				{#if eventsLoading}
					<Skeleton class="h-40 bg-surface-1" />
				{:else}
					{@const results = filteredEvents()}
					{#if results.length === 0}
						<div class="py-12 text-center">
							<p class="text-[13px] text-fg-faint">No delegation events yet.</p>
							<p class="mt-1 text-[12px] text-fg-faint/60">Run this composition with <code class="font-mono">initrunner compose up</code> to see routing activity.</p>
						</div>
					{:else}
						<div class="border border-edge">
							<table class="w-full text-[12px]">
								<thead>
									<tr class="border-b border-edge bg-surface-1 text-left text-fg-faint">
										<th class="px-3 py-2 font-medium">Status</th>
										<th class="px-3 py-2 font-medium">Source</th>
										<th class="px-3 py-2 font-medium">Target</th>
										<th class="px-3 py-2 font-medium">Time</th>
										<th class="px-3 py-2 font-medium">Run ID</th>
									</tr>
								</thead>
								<tbody>
									{#each results as event}
										<tr class="border-b border-edge/50 transition-[background-color] duration-100 hover:bg-surface-1/50">
											<td class="px-3 py-2">
												<span class="inline-flex items-center gap-1.5">
													<span class="h-2 w-2 rounded-full {statusColor(event.status)}" style="box-shadow: 0 0 4px {event.status === 'delivered' ? 'oklch(0.72 0.17 142)' : event.status === 'dropped' || event.status === 'error' ? 'oklch(0.65 0.20 25)' : 'oklch(0.80 0.18 85)'}"></span>
													<span class="font-mono text-fg-muted">{event.status}</span>
												</span>
											</td>
											<td class="px-3 py-2 font-mono text-fg-muted">{event.source_service}</td>
											<td class="px-3 py-2 font-mono text-fg-muted">{event.target_service}</td>
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
		</div>
	{:else}
		<p class="text-[13px] text-fg-faint">Composition not found.</p>
	{/if}
</div>
