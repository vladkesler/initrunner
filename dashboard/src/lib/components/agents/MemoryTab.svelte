<script lang="ts">
	import { onMount } from 'svelte';
	import {
		getAgentMemories,
		getAgentSessions,
		getAgentSession,
		consolidateMemories
	} from '$lib/api/agents';
	import type { MemoryItem, SessionSummary, SessionDetail } from '$lib/api/types';
	import { Skeleton } from '$lib/components/ui/skeleton';
	import { RefreshCw, Sparkles, ChevronRight } from 'lucide-svelte';
	import { toast } from '$lib/stores/toast.svelte';

	let { agentId, hasMemory, refreshKey = 0 }: { agentId: string; hasMemory: boolean; refreshKey?: number } = $props();

	// Sub-view toggle
	let view = $state<'memories' | 'sessions'>('memories');

	// Memories state
	let memories = $state<MemoryItem[]>([]);
	let memoriesLoading = $state(true);
	let typeFilter = $state<string>('all');
	let consolidating = $state(false);
	let consolidateResult = $state<number | null>(null);

	const filteredMemories = $derived(
		typeFilter === 'all' ? memories : memories.filter((m) => m.memory_type === typeFilter)
	);

	// Sessions state
	let sessions = $state<SessionSummary[]>([]);
	let sessionsLoading = $state(true);
	let expandedSessionId = $state<string | null>(null);
	let expandedSession = $state<SessionDetail | null>(null);
	let sessionLoading = $state(false);

	async function loadMemories() {
		memoriesLoading = true;
		try {
			memories = await getAgentMemories(agentId);
		} catch {
			toast.error('Failed to load memories');
		} finally {
			memoriesLoading = false;
		}
	}

	async function loadSessions() {
		sessionsLoading = true;
		try {
			sessions = await getAgentSessions(agentId);
		} catch {
			toast.error('Failed to load sessions');
		} finally {
			sessionsLoading = false;
		}
	}

	async function handleConsolidate() {
		consolidating = true;
		consolidateResult = null;
		try {
			const result = await consolidateMemories(agentId);
			consolidateResult = result.consolidated;
			await loadMemories();
		} catch {
			toast.error('Failed to consolidate memories');
		} finally {
			consolidating = false;
		}
	}

	async function toggleSession(sessionId: string) {
		if (expandedSessionId === sessionId) {
			expandedSessionId = null;
			expandedSession = null;
			return;
		}
		expandedSessionId = sessionId;
		expandedSession = null;
		sessionLoading = true;
		try {
			expandedSession = await getAgentSession(agentId, sessionId);
		} catch {
			toast.error('Failed to load session detail');
		} finally {
			sessionLoading = false;
		}
	}

	function formatDate(ts: string): string {
		try {
			const d = new Date(ts);
			return d.toLocaleDateString([], { month: 'short', day: 'numeric' }) +
				' ' +
				d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
		} catch {
			return ts;
		}
	}

	function truncate(text: string, len: number): string {
		if (!text) return '';
		return text.length > len ? text.slice(0, len) + '\u2026' : text;
	}

	let mounted = $state(false);

	onMount(() => {
		if (hasMemory) {
			loadMemories();
			loadSessions();
		}
		mounted = true;
	});

	// Auto-refresh when refreshKey changes (after a run completes)
	$effect(() => {
		const _key = refreshKey;
		if (mounted && _key > 0 && hasMemory) {
			loadMemories();
			loadSessions();
		}
	});
</script>

{#if !hasMemory}
	<div class="flex flex-col items-center justify-center py-16 text-center">
		<p class="text-[13px] text-fg-faint">This agent has no memory configuration.</p>
		<p class="mt-1 text-[12px] text-fg-faint">
			Add an episodic, semantic, or procedural memory block to the role YAML to enable memory browsing.
		</p>
	</div>
{:else}
	<div class="space-y-4">
		<!-- Sub-view toggle -->
		<div class="flex items-center gap-3">
			<div class="flex items-center gap-0.5 rounded-full border border-edge bg-surface-1 p-0.5">
				<button
					class="rounded-full px-2.5 py-1 text-[13px] font-medium transition-[color,background-color] duration-150"
					class:bg-surface-2={view === 'memories'}
					class:text-fg={view === 'memories'}
					class:text-fg-faint={view !== 'memories'}
					onclick={() => (view = 'memories')}
				>
					Memories
				</button>
				<button
					class="rounded-full px-2.5 py-1 text-[13px] font-medium transition-[color,background-color] duration-150"
					class:bg-surface-2={view === 'sessions'}
					class:text-fg={view === 'sessions'}
					class:text-fg-faint={view !== 'sessions'}
					onclick={() => (view = 'sessions')}
				>
					Sessions
				</button>
			</div>

			{#if view === 'memories'}
				<!-- Type filter -->
				<div class="flex items-center gap-0.5 rounded-full border border-edge bg-surface-1 p-0.5">
					{#each ['all', 'episodic', 'semantic', 'procedural'] as type}
						<button
							class="rounded-full px-2.5 py-1 text-[13px] font-medium capitalize transition-[color,background-color] duration-150"
							class:bg-surface-2={typeFilter === type}
							class:text-fg={typeFilter === type}
							class:text-fg-faint={typeFilter !== type}
							onclick={() => (typeFilter = type)}
						>
							{type}
						</button>
					{/each}
				</div>

				<div class="ml-auto flex items-center gap-2">
					{#if consolidateResult !== null}
						<span class="text-[12px] text-ok">{consolidateResult} consolidated</span>
					{/if}
					<button
						class="inline-flex items-center gap-1.5 rounded-full border border-edge px-3 py-1.5 text-[13px] text-fg-faint transition-[color,background-color,border-color] duration-150 hover:border-accent-primary/20 hover:bg-surface-2 hover:text-fg-muted disabled:opacity-40"
						onclick={handleConsolidate}
						disabled={consolidating}
					>
						<Sparkles size={12} />
						{consolidating ? 'Consolidating...' : 'Consolidate'}
					</button>
					<button
						class="inline-flex items-center gap-1.5 rounded-full border border-edge px-3 py-1.5 text-[13px] text-fg-faint transition-[color,background-color,border-color] duration-150 hover:border-accent-primary/20 hover:bg-surface-2 hover:text-fg-muted"
						onclick={loadMemories}
						aria-label="Refresh"
					>
						<RefreshCw size={12} />
					</button>
				</div>
			{:else}
				<button
					class="ml-auto inline-flex items-center gap-1.5 rounded-full border border-edge px-3 py-1.5 text-[13px] text-fg-faint transition-[color,background-color,border-color] duration-150 hover:border-accent-primary/20 hover:bg-surface-2 hover:text-fg-muted"
					onclick={loadSessions}
					aria-label="Refresh"
				>
					<RefreshCw size={12} />
				</button>
			{/if}
		</div>

		<!-- Memories view -->
		{#if view === 'memories'}
			{#if memoriesLoading}
				<Skeleton class="h-48 bg-surface-1" />
			{:else if filteredMemories.length === 0}
				<div class="flex items-center justify-center py-16 text-[13px] text-fg-faint">
					No memories found
				</div>
			{:else}
				<div class="space-y-2">
					{#each filteredMemories as memory (memory.id)}
						<div class="card-surface bg-surface-1 p-3">
							<div class="flex items-start gap-2">
								<p class="flex-1 font-mono text-[13px] leading-relaxed text-fg-muted" style="display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden;">
									{memory.content}
								</p>
							</div>
							<div class="mt-2 flex items-center gap-2">
								<span class="rounded-[2px] bg-accent-primary/10 px-2 py-0.5 font-mono text-[11px] text-accent-primary">
									{memory.memory_type}
								</span>
								{#if memory.category}
									<span class="rounded-full bg-surface-2 px-2 py-0.5 font-mono text-[11px] text-fg-faint">
										{memory.category}
									</span>
								{/if}
								<span class="ml-auto text-[11px] text-fg-faint">{formatDate(memory.created_at)}</span>
								{#if memory.consolidated_at}
									<span class="text-[11px] text-fg-faint">consolidated</span>
								{/if}
							</div>
						</div>
					{/each}
				</div>
				<p class="text-[12px] text-fg-faint">{filteredMemories.length} memories</p>
			{/if}
		{/if}

		<!-- Sessions view -->
		{#if view === 'sessions'}
			{#if sessionsLoading}
				<Skeleton class="h-48 bg-surface-1" />
			{:else if sessions.length === 0}
				<div class="flex items-center justify-center py-16 text-[13px] text-fg-faint">
					No sessions found
				</div>
			{:else}
				<div class="space-y-1">
					{#each sessions as session (session.session_id)}
						<div>
							<button
								class="flex w-full items-center gap-3 border border-edge bg-surface-1 px-3 py-2.5 text-left transition-[background-color] duration-150 hover:bg-surface-2"
								onclick={() => toggleSession(session.session_id)}
							>
								<ChevronRight
									size={12}
									class="shrink-0 text-fg-faint transition-transform duration-150 {expandedSessionId === session.session_id ? 'rotate-90' : ''}"
								/>
								<div class="flex-1 min-w-0">
									<div class="flex items-center gap-2">
										<span class="font-mono text-[13px] text-fg-muted">{truncate(session.preview, 60)}</span>
									</div>
								</div>
								<span class="shrink-0 font-mono text-[12px] text-fg-faint" style="font-variant-numeric: tabular-nums">
									{session.message_count} msgs
								</span>
								<span class="shrink-0 text-[12px] text-fg-faint">{formatDate(session.timestamp)}</span>
							</button>

							<!-- Expanded session content -->
							{#if expandedSessionId === session.session_id}
								<div class="border-x border-b border-edge bg-surface-0 p-4">
									{#if sessionLoading}
										<Skeleton class="h-24 bg-surface-1" />
									{:else if expandedSession}
										<div class="space-y-3">
											{#each expandedSession.messages as message}
												<div class="flex gap-3">
													<span class="shrink-0 section-label {message.role === 'user' ? 'text-accent-primary' : 'text-accent-secondary'}">
														{message.role === 'user' ? 'YOU' : 'AI'}
													</span>
													<p class="flex-1 font-mono text-[13px] leading-relaxed text-fg-muted whitespace-pre-wrap">
														{message.content}
													</p>
												</div>
											{/each}
										</div>
									{:else}
										<p class="text-[13px] text-fg-faint">Failed to load session</p>
									{/if}
								</div>
							{/if}
						</div>
					{/each}
				</div>
				<p class="text-[12px] text-fg-faint">{sessions.length} sessions</p>
			{/if}
		{/if}
	</div>
{/if}
