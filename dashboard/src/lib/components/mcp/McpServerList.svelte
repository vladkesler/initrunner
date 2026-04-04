<script lang="ts">
	import type { McpServer } from '$lib/api/types';
	import { checkMcpServerHealth } from '$lib/api/mcp';
	import McpServerCard from './McpServerCard.svelte';
	import { Search, RefreshCw } from 'lucide-svelte';

	let {
		servers,
		openPlayground
	}: {
		servers: McpServer[];
		openPlayground: (serverId: string, toolName: string) => void;
	} = $props();

	let transportFilter = $state('all');
	let query = $state('');
	let healthChecking = $state(false);

	const transports = ['all', 'stdio', 'sse', 'streamable-http'] as const;

	const filtered = $derived.by(() => {
		let result = servers;
		if (transportFilter !== 'all') {
			result = result.filter((s) => s.transport === transportFilter);
		}
		if (query) {
			const q = query.toLowerCase();
			result = result.filter(
				(s) =>
					s.display_name.toLowerCase().includes(q) ||
					s.agent_refs.some((r) => r.agent_name.toLowerCase().includes(q))
			);
		}
		return result;
	});

	async function checkAllHealth() {
		healthChecking = true;
		try {
			await Promise.allSettled(servers.map((s) => checkMcpServerHealth(s.server_id)));
			// The page would need to re-fetch servers to see updated health.
			// For now, we note the checks were triggered.
		} finally {
			healthChecking = false;
		}
	}
</script>

<div class="flex flex-col gap-4">
	<!-- Filter bar -->
	<div class="flex items-center gap-3">
		<!-- Transport pills -->
		<div class="flex gap-1.5">
			{#each transports as t}
				<button
					class="rounded-full border px-2.5 py-1 font-mono text-[12px] transition-colors
						{transportFilter === t
							? 'border-accent-primary-dim/40 bg-accent-primary-wash text-fg'
							: 'border-edge bg-transparent text-fg-faint hover:text-fg-muted'}"
					onclick={() => (transportFilter = t)}
				>
					{t === 'all' ? 'All' : t}
				</button>
			{/each}
		</div>

		<!-- Search -->
		<div class="relative ml-auto">
			<Search
				size={13}
				class="absolute left-2.5 top-1/2 -translate-y-1/2 text-fg-faint"
			/>
			<input
				type="text"
				placeholder="Filter servers..."
				bind:value={query}
				class="h-8 w-56 border border-edge bg-surface-1 pl-8 pr-3 text-[13px] text-fg placeholder:text-fg-faint focus:border-accent-primary-dim/60 focus:shadow-[0_0_0_3px_oklch(0.75_0.15_128/0.08)] focus:outline-none"
			/>
		</div>

		<!-- Health check all -->
		<button
			class="flex items-center gap-1.5 rounded-[2px] border border-edge px-2.5 py-1.5 text-[13px] text-fg-muted transition-colors hover:border-accent-primary-dim hover:text-fg"
			onclick={checkAllHealth}
			disabled={healthChecking}
		>
			<RefreshCw size={13} class={healthChecking ? 'animate-spin' : ''} />
			{healthChecking ? 'Checking...' : 'Check Health'}
		</button>
	</div>

	<!-- Server cards -->
	{#if filtered.length === 0}
		<div class="border border-edge bg-surface-1 p-8 text-center text-[13px] text-fg-faint">
			{servers.length === 0
				? 'No MCP servers configured in any agent. Add a tool with type: mcp to a role.yaml to get started.'
				: 'No servers match the current filters.'}
		</div>
	{:else}
		<div class="flex flex-col gap-2">
			{#each filtered as server (server.server_id)}
				<McpServerCard {server} {openPlayground} />
			{/each}
		</div>
	{/if}
</div>
