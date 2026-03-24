<script lang="ts">
	import { onMount } from 'svelte';
	import { request } from '$lib/api/client';
	import { runDoctor, listToolTypes } from '$lib/api/system';
	import type { Provider, HealthStatus, DoctorCheck, ToolType } from '$lib/api/types';
	import { Skeleton } from '$lib/components/ui/skeleton';
	import { Stethoscope, RefreshCw, CheckCircle, AlertTriangle, XCircle, Wrench } from 'lucide-svelte';

	let version = $state('');
	let providers = $state<Provider[]>([]);
	let doctorChecks = $state<DoctorCheck[]>([]);
	let tools = $state<ToolType[]>([]);
	let loading = $state(true);
	let doctorLoading = $state(false);
	let toolsLoading = $state(true);

	function statusIcon(status: string) {
		if (status === 'ok') return CheckCircle;
		if (status === 'warn') return AlertTriangle;
		return XCircle;
	}

	function statusColor(status: string): string {
		if (status === 'ok') return 'text-ok';
		if (status === 'warn') return 'text-warn';
		return 'text-fail';
	}

	async function loadDoctor() {
		doctorLoading = true;
		try {
			const res = await runDoctor();
			doctorChecks = res.checks;
		} catch {
			// API not available
		} finally {
			doctorLoading = false;
		}
	}

	onMount(async () => {
		try {
			const [health, p, t] = await Promise.all([
				request<HealthStatus>('/api/health'),
				request<Provider[]>('/api/providers'),
				listToolTypes()
			]);
			version = health.version;
			providers = p;
			tools = t;
		} catch {
			// API not available
		} finally {
			loading = false;
			toolsLoading = false;
		}
	});
</script>

<div class="space-y-8">
	<!-- Header -->
	<div class="flex items-center gap-3">
		<h1 class="text-xl font-semibold tracking-[-0.02em] text-fg">System</h1>
		{#if version}
			<span class="border border-edge bg-surface-1 px-2 py-0.5 font-mono text-[12px] text-fg-faint">v{version}</span>
		{/if}
	</div>

	{#if loading}
		<Skeleton class="h-40 bg-surface-1" />
	{:else}
		<!-- Providers -->
		<div>
			<h2 class="mb-3 font-mono text-[12px] font-medium uppercase tracking-[0.1em] text-fg-faint">Providers</h2>
			{#if providers.length === 0}
				<div class="border border-edge bg-surface-1 px-4 py-8 text-center text-[13px] text-fg-faint">
					No providers detected. Set API keys to get started.
				</div>
			{:else}
				<div class="overflow-hidden border border-edge">
					<table class="w-full">
						<thead>
							<tr class="border-b-2 border-edge">
								<th class="px-4 py-2 text-left text-[12px] font-medium uppercase tracking-[0.1em] text-fg-faint">Provider</th>
								<th class="px-4 py-2 text-left text-[12px] font-medium uppercase tracking-[0.1em] text-fg-faint">Default Model</th>
							</tr>
						</thead>
						<tbody>
							{#each providers as p}
								<tr class="border-b border-edge-subtle transition-[background-color] duration-150 hover:bg-accent-primary/[0.03]">
									<td class="px-4 py-2 font-mono text-[13px] text-fg-muted">{p.provider}</td>
									<td class="px-4 py-2 font-mono text-[13px] text-fg-faint">{p.model}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{/if}
		</div>

		<!-- Doctor -->
		<div>
			<div class="mb-3 flex items-center gap-3">
				<h2 class="font-mono text-[12px] font-medium uppercase tracking-[0.1em] text-fg-faint">Health Check</h2>
				<button
					class="flex items-center gap-1.5 rounded-full border border-edge px-3 py-1 text-[13px] text-fg-faint transition-[color,background-color,border-color] duration-150 hover:bg-surface-2 hover:text-fg-muted hover:border-accent-primary/20"
					class:opacity-50={doctorLoading}
					onclick={loadDoctor}
					disabled={doctorLoading}
				>
					{#if doctorLoading}
						<RefreshCw size={11} class="animate-spin" />
						Checking...
					{:else}
						<Stethoscope size={11} />
						Run Doctor
					{/if}
				</button>
			</div>

			{#if doctorChecks.length === 0 && !doctorLoading}
				<div class="border border-edge bg-surface-1 px-4 py-8 text-center text-[13px] text-fg-faint">
					Click "Run Doctor" to check provider connectivity and SDK availability.
				</div>
			{:else if doctorChecks.length > 0}
				<div class="space-y-1">
					{#each doctorChecks as check}
						{@const Icon = statusIcon(check.status)}
						<div class="card-surface flex items-center gap-3 bg-surface-1 px-4 py-2.5">
							<Icon size={14} class={statusColor(check.status)} />
							<span class="font-mono text-[13px] text-fg-muted">{check.name}</span>
							<span class="ml-auto text-[13px] {statusColor(check.status)}">{check.message}</span>
						</div>
					{/each}
				</div>
			{/if}
		</div>

		<!-- Tool Registry -->
		<div>
			<h2 class="mb-3 flex items-center gap-2 font-mono text-[12px] font-medium uppercase tracking-[0.1em] text-fg-faint">
				<Wrench size={12} />
				Tool Registry
				{#if tools.length > 0}
					<span class="rounded-full border border-edge bg-surface-2 px-2 py-0.5 text-[11px]">{tools.length}</span>
				{/if}
			</h2>

			{#if toolsLoading}
				<Skeleton class="h-32 bg-surface-1" />
			{:else if tools.length === 0}
				<div class="border border-edge bg-surface-1 px-4 py-8 text-center text-[13px] text-fg-faint">
					No tool types registered.
				</div>
			{:else}
				<div class="overflow-hidden border border-edge">
					<div class="grid grid-cols-1 divide-y divide-edge-subtle md:grid-cols-2 md:divide-y-0">
						{#each tools as tool, i}
							<div
								class="px-4 py-2.5"
								class:border-r={i % 2 === 0}
								class:border-edge-subtle={i % 2 === 0}
								class:border-b={i < tools.length - (tools.length % 2 === 0 ? 2 : 1)}
								class:border-b-edge-subtle={i < tools.length - (tools.length % 2 === 0 ? 2 : 1)}
							>
								<div class="font-mono text-[13px] text-fg-muted">{tool.name}</div>
								<div class="mt-0.5 text-[13px] text-fg-faint">{tool.description}</div>
							</div>
						{/each}
					</div>
				</div>
			{/if}
		</div>
	{/if}
</div>
