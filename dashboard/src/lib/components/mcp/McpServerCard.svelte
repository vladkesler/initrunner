<script lang="ts">
	import type { McpServer, McpTool } from '$lib/api/types';
	import { getMcpServerTools, checkMcpServerHealth, invalidateMcpCache } from '$lib/api/mcp';
	import { ChevronDown, ChevronRight, Play, RefreshCw, Trash2 } from 'lucide-svelte';
	import { Skeleton } from '$lib/components/ui/skeleton';

	let {
		server,
		openPlayground
	}: {
		server: McpServer;
		openPlayground: (serverId: string, toolName: string) => void;
	} = $props();

	let expanded = $state(false);
	let tools = $state<McpTool[]>([]);
	let toolsLoading = $state(false);
	let toolsLoaded = $state(false);
	let toolsError = $state<string | null>(null);
	let healthChecking = $state(false);

	// Local health state (updates on check)
	let healthStatus = $derived(server.health_status);

	async function toggle() {
		expanded = !expanded;
		if (expanded && !toolsLoaded) {
			toolsLoading = true;
			toolsError = null;
			try {
				tools = await getMcpServerTools(server.server_id);
				toolsLoaded = true;
			} catch (err) {
				tools = [];
				toolsError = err instanceof Error ? err.message : String(err);
			} finally {
				toolsLoading = false;
			}
		}
	}

	async function checkHealth(e: MouseEvent) {
		e.stopPropagation();
		healthChecking = true;
		try {
			const result = await checkMcpServerHealth(server.server_id);
			server.health_status = result.status;
			server.health_checked_at = result.checked_at;
		} catch {
			/* ignore */
		} finally {
			healthChecking = false;
		}
	}

	let cacheInvalidating = $state(false);

	async function invalidateCache(e: MouseEvent) {
		e.stopPropagation();
		cacheInvalidating = true;
		try {
			await invalidateMcpCache(server.server_id);
			server.cache_age_seconds = null;
		} catch {
			/* ignore */
		} finally {
			cacheInvalidating = false;
		}
	}

	function testTool(e: MouseEvent, toolName: string) {
		e.stopPropagation();
		openPlayground(server.server_id, toolName);
	}

	function formatCacheAge(seconds: number): string {
		if (seconds < 60) return `${Math.round(seconds)}s ago`;
		if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
		if (seconds < 86400) return `${Math.round(seconds / 3600)}h ago`;
		return `${Math.round(seconds / 86400)}d ago`;
	}

	let hasDeferredRef = $derived(server.agent_refs.some((r) => r.defer));

	const transportColors: Record<string, string> = {
		stdio: 'border-accent-secondary-muted text-accent-secondary',
		sse: 'border-accent-primary-dim/40 text-accent-primary-dim',
		'streamable-http': 'border-info/30 text-info'
	};

	function healthColor(status: string | null): string {
		if (status === 'healthy') return 'var(--color-ok)';
		if (status === 'degraded') return 'var(--color-warn)';
		if (status === 'unhealthy') return 'var(--color-fail)';
		return 'var(--color-fg-faint)';
	}
</script>

<div class="card-surface">
	<!-- Header row -->
	<div class="flex w-full items-center gap-3 px-4 py-3">
		<!-- Expand chevron (clickable) -->
		<button class="text-fg-faint" onclick={toggle}>
			{#if expanded}
				<ChevronDown size={14} />
			{:else}
				<ChevronRight size={14} />
			{/if}
		</button>

		<!-- Health dot -->
		<span
			class="status-dot shrink-0"
			style="background: {healthColor(healthStatus)}"
			title={healthStatus ?? 'unknown'}
		></span>

		<!-- Server name (clickable to expand) -->
		<button class="min-w-0 truncate font-mono text-[13px] text-fg text-left" onclick={toggle}>
			{server.display_name}
		</button>

		<!-- Transport badge -->
		<span
			class="shrink-0 rounded-full border px-2 py-0.5 font-mono text-[11px] {transportColors[
				server.transport
			] ?? 'border-edge text-fg-faint'}"
		>
			{server.transport}
		</span>

		<!-- Agent chips -->
		<div class="ml-auto flex items-center gap-1.5">
			{#each server.agent_refs as ref}
				<a
					href="/agents/{ref.agent_id}"
					class="flex items-center gap-1 rounded-full border border-edge bg-surface-2 px-2 py-0.5 font-mono text-[11px] text-fg-faint transition-colors hover:border-accent-primary-dim/40 hover:text-fg-muted"
					title={ref.role_path}
				>
					{ref.agent_name}
					{#if ref.defer}
						<span class="rounded-full border border-warn/30 px-1 text-[9px] text-warn">deferred</span>
					{/if}
				</a>
			{/each}
		</div>

		<!-- Cache age + invalidate -->
		{#if server.cache_age_seconds != null}
			<span class="font-mono text-[10px] text-fg-faint" title="Schema cache age">
				cached {formatCacheAge(server.cache_age_seconds)}
			</span>
			<button
				class="shrink-0 rounded-[2px] border border-edge p-1 text-fg-faint transition-colors hover:border-warn hover:text-warn"
				onclick={invalidateCache}
				disabled={cacheInvalidating}
				title="Invalidate schema cache"
			>
				<Trash2 size={10} />
			</button>
		{/if}

		<!-- Health check button -->
		<button
			class="shrink-0 rounded-[2px] border border-edge p-1 text-fg-faint transition-colors hover:border-accent-primary-dim hover:text-fg-muted"
			onclick={checkHealth}
			disabled={healthChecking}
			title="Check health"
		>
			<RefreshCw size={12} class={healthChecking ? 'animate-spin' : ''} />
		</button>
	</div>

	<!-- Expanded tool list -->
	{#if expanded}
		<div class="border-t border-edge-subtle px-4 py-3">
			{#if toolsLoading}
				<div class="flex flex-col gap-2">
					<Skeleton class="h-6 w-full" />
					<Skeleton class="h-6 w-full" />
					<Skeleton class="h-6 w-3/4" />
				</div>
			{:else if toolsError}
				<p class="text-[13px] text-fail">{toolsError}</p>
			{:else if tools.length === 0}
				<p class="text-[13px] text-fg-faint">No tools available.</p>
			{:else}
				<div class="section-label mb-2" style="font-size: 10px; letter-spacing: 0.14em">
					{tools.length} TOOL{tools.length !== 1 ? 'S' : ''}
				</div>
				<div class="flex flex-col gap-1">
					{#each tools as tool}
						<div
							class="group flex items-center gap-3 border-b border-edge-ghost py-2 last:border-b-0"
						>
							<span class="min-w-0 shrink-0 font-mono text-[13px] text-fg">
								{tool.name}
							</span>
							<span class="min-w-0 truncate text-[12px] text-fg-faint">
								{tool.description}
							</span>
							<button
								class="ml-auto flex shrink-0 items-center gap-1 rounded-[2px] border border-edge px-2 py-0.5 font-mono text-[11px] text-fg-faint opacity-0 transition-all group-hover:opacity-100 hover:border-accent-primary-dim hover:text-fg"
								onclick={(e) => testTool(e, tool.name)}
							>
								<Play size={10} />
								Test
							</button>
						</div>
					{/each}
				</div>
			{/if}
		</div>
	{/if}
</div>
