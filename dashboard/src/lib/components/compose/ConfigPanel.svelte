<script lang="ts">
	import type { ComposeDetail, ComposeServiceDetail } from '$lib/api/types';
	import ConfigSection from '$lib/components/agents/ConfigSection.svelte';
	import { Database, ArrowRight, Zap, ShieldAlert, HeartPulse, RefreshCw, Box } from 'lucide-svelte';

	let { detail }: { detail: ComposeDetail } = $props();
</script>

<div class="space-y-1">
	<!-- Per-service sections -->
	{#each detail.services as svc (svc.name)}
		<ConfigSection title={svc.name} defaultOpen={detail.services.length <= 4}>
			<div class="space-y-3 text-[12px]">
				<!-- Role -->
				<div>
					<span class="text-fg-faint">Role:</span>
					<span class="ml-1 font-mono text-fg-muted">{svc.role_path}</span>
				</div>

				<!-- Sink -->
				{#if svc.sink}
					<div class="space-y-1 border-l-2 border-l-accent-primary/20 pl-3">
						<div class="flex items-center gap-1.5 text-fg-faint">
							<ArrowRight size={11} strokeWidth={1.5} />
							<span class="font-medium">Sink</span>
						</div>
						<div class="grid grid-cols-2 gap-x-4 gap-y-1 font-mono text-fg-muted">
							<span class="text-fg-faint">strategy</span>
							<span>{svc.sink.strategy}</span>
							<span class="text-fg-faint">targets</span>
							<span>{svc.sink.targets.join(', ')}</span>
							<span class="text-fg-faint">queue_size</span>
							<span class="tabular-nums">{svc.sink.queue_size}</span>
							<span class="text-fg-faint">timeout</span>
							<span class="tabular-nums">{svc.sink.timeout_seconds}s</span>
							{#if svc.sink.circuit_breaker_threshold !== null}
								<span class="text-fg-faint">circuit breaker</span>
								<span class="tabular-nums">{svc.sink.circuit_breaker_threshold} failures</span>
							{/if}
						</div>
					</div>
				{/if}

				<!-- Trigger -->
				{#if svc.trigger_summary}
					<div class="flex items-center gap-1.5">
						<Zap size={11} strokeWidth={1.5} class="text-accent-secondary" />
						<span class="text-fg-faint">Trigger:</span>
						<span class="font-mono text-fg-muted">{svc.trigger_summary}</span>
					</div>
				{/if}

				<!-- Restart -->
				{#if svc.restart.condition !== 'none'}
					<div class="space-y-1 border-l-2 border-l-fg-faint/20 pl-3">
						<div class="flex items-center gap-1.5 text-fg-faint">
							<RefreshCw size={11} strokeWidth={1.5} />
							<span class="font-medium">Restart</span>
						</div>
						<div class="grid grid-cols-2 gap-x-4 gap-y-1 font-mono text-fg-muted">
							<span class="text-fg-faint">condition</span>
							<span>{svc.restart.condition}</span>
							<span class="text-fg-faint">max_retries</span>
							<span class="tabular-nums">{svc.restart.max_retries}</span>
							<span class="text-fg-faint">delay</span>
							<span class="tabular-nums">{svc.restart.delay_seconds}s</span>
						</div>
					</div>
				{/if}

				<!-- Health check (show only if non-default) -->
				{#if svc.health_check.interval_seconds !== 30 || svc.health_check.timeout_seconds !== 10 || svc.health_check.retries !== 3}
					<div class="space-y-1 border-l-2 border-l-status-ok/20 pl-3">
						<div class="flex items-center gap-1.5 text-fg-faint">
							<HeartPulse size={11} strokeWidth={1.5} />
							<span class="font-medium">Health Check</span>
						</div>
						<div class="grid grid-cols-2 gap-x-4 gap-y-1 font-mono text-fg-muted">
							<span class="text-fg-faint">interval</span>
							<span class="tabular-nums">{svc.health_check.interval_seconds}s</span>
							<span class="text-fg-faint">timeout</span>
							<span class="tabular-nums">{svc.health_check.timeout_seconds}s</span>
							<span class="text-fg-faint">retries</span>
							<span class="tabular-nums">{svc.health_check.retries}</span>
						</div>
					</div>
				{/if}

				<!-- Dependencies -->
				{#if svc.depends_on.length > 0}
					<div class="flex items-center gap-1.5">
						<Box size={11} strokeWidth={1.5} class="text-fg-faint" />
						<span class="text-fg-faint">Depends on:</span>
						<span class="font-mono text-fg-muted">{svc.depends_on.join(', ')}</span>
					</div>
				{/if}

				<!-- Environment -->
				{#if svc.environment_count > 0}
					<div class="text-fg-faint">
						{svc.environment_count} environment variable{svc.environment_count !== 1 ? 's' : ''}
					</div>
				{/if}
			</div>
		</ConfigSection>
	{/each}

	<!-- Shared resources -->
	{#if detail.shared_memory_enabled || detail.shared_documents_enabled}
		<ConfigSection title="Shared Resources" defaultOpen={true}>
			<div class="flex flex-wrap gap-2">
				{#if detail.shared_memory_enabled}
					<span class="flex items-center gap-1 border border-edge bg-surface-1 px-2 py-0.5 font-mono text-[11px] text-fg-faint">
						<Database size={10} />
						Shared memory
					</span>
				{/if}
				{#if detail.shared_documents_enabled}
					<span class="flex items-center gap-1 border border-edge bg-surface-1 px-2 py-0.5 font-mono text-[11px] text-fg-faint">
						<Database size={10} />
						Shared documents
					</span>
				{/if}
			</div>
		</ConfigSection>
	{/if}
</div>
