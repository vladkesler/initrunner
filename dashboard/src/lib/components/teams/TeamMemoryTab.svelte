<script lang="ts">
	import { onMount } from 'svelte';
	import { getTeamMemories, consolidateTeamMemories } from '$lib/api/teams';
	import type { MemoryItem } from '$lib/api/types';
	import { Skeleton } from '$lib/components/ui/skeleton';
	import { RefreshCw, Sparkles } from 'lucide-svelte';
	import { toast } from '$lib/stores/toast.svelte';

	let { teamId, hasMemory, refreshKey = 0 }: { teamId: string; hasMemory: boolean; refreshKey?: number } = $props();

	let memories = $state<MemoryItem[]>([]);
	let memoriesLoading = $state(true);
	let typeFilter = $state<string>('all');
	let consolidating = $state(false);
	let consolidateResult = $state<number | null>(null);

	const filteredMemories = $derived(
		typeFilter === 'all' ? memories : memories.filter((m) => m.memory_type === typeFilter)
	);

	async function loadMemories() {
		memoriesLoading = true;
		try {
			memories = await getTeamMemories(teamId);
		} catch {
			toast.error('Failed to load memories');
		} finally {
			memoriesLoading = false;
		}
	}

	async function handleConsolidate() {
		consolidating = true;
		consolidateResult = null;
		try {
			const result = await consolidateTeamMemories(teamId);
			consolidateResult = result.consolidated;
			await loadMemories();
		} catch {
			toast.error('Failed to consolidate memories');
		} finally {
			consolidating = false;
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

	let mounted = $state(false);

	onMount(() => {
		if (hasMemory) {
			loadMemories();
		}
		mounted = true;
	});

	$effect(() => {
		const _key = refreshKey;
		if (mounted && _key > 0 && hasMemory) {
			loadMemories();
		}
	});
</script>

{#if !hasMemory}
	<div class="flex flex-col items-center justify-center py-16 text-center">
		<p class="text-[13px] text-fg-faint">This team has no shared memory configuration.</p>
		<p class="mt-1 text-[12px] text-fg-faint">
			Add a shared_memory block with enabled: true to the team YAML to enable memory browsing.
		</p>
	</div>
{:else}
	<div class="space-y-4">
		<!-- Type filter + actions -->
		<div class="flex items-center gap-3">
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
		</div>

		<!-- Memories list -->
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
	</div>
{/if}
