<script lang="ts">
	import { onMount } from 'svelte';
	import { getMcpRegistry } from '$lib/api/mcp';
	import type { McpRegistryEntry } from '$lib/api/types';
	import { Skeleton } from '$lib/components/ui/skeleton';
	import { Search, Copy, Check } from 'lucide-svelte';
	import { toast } from '$lib/stores/toast.svelte';

	let entries = $state<McpRegistryEntry[]>([]);
	let loading = $state(true);
	let query = $state('');
	let activeCategory = $state('all');

	const categories = [
		'all',
		'filesystem',
		'database',
		'web',
		'developer',
		'productivity',
		'communication'
	];

	const filtered = $derived.by(() => {
		let result = entries;
		if (activeCategory !== 'all') {
			result = result.filter((e) => e.category === activeCategory);
		}
		if (query) {
			const q = query.toLowerCase();
			result = result.filter(
				(e) =>
					e.display_name.toLowerCase().includes(q) ||
					e.description.toLowerCase().includes(q) ||
					e.tags.some((t) => t.includes(q))
			);
		}
		return result;
	});

	onMount(async () => {
		try {
			entries = await getMcpRegistry();
		} catch {
			/* ignore */
		} finally {
			loading = false;
		}
	});

	let copiedName = $state<string | null>(null);

	function copyYaml(entry: McpRegistryEntry) {
		const lines = [`- type: mcp`, `  transport: ${entry.transport}`];
		if (entry.command) {
			lines.push(`  command: ${entry.command}`);
			if (entry.args.length > 0) {
				lines.push(`  args:`);
				for (const a of entry.args) lines.push(`    - "${a}"`);
			}
		}
		if (entry.url) {
			lines.push(`  url: ${entry.url}`);
		}
		navigator.clipboard.writeText(lines.join('\n'));
		copiedName = entry.name;
		toast.success('YAML snippet copied');
		setTimeout(() => {
			copiedName = null;
		}, 2000);
	}
</script>

<div class="flex flex-col gap-4">
	<!-- Filter bar -->
	<div class="flex items-center gap-3">
		<div class="flex flex-wrap gap-1.5">
			{#each categories as cat}
				<button
					class="rounded-full border px-2.5 py-1 text-[12px] capitalize transition-colors
						{activeCategory === cat
							? 'border-accent-primary-dim/40 bg-accent-primary-wash text-fg'
							: 'border-edge bg-transparent text-fg-faint hover:text-fg-muted'}"
					onclick={() => (activeCategory = cat)}
				>
					{cat}
				</button>
			{/each}
		</div>

		<div class="relative ml-auto">
			<Search size={13} class="absolute left-2.5 top-1/2 -translate-y-1/2 text-fg-faint" />
			<input
				type="text"
				placeholder="Search servers..."
				bind:value={query}
				class="h-8 w-56 border border-edge bg-surface-1 pl-8 pr-3 text-[13px] text-fg placeholder:text-fg-faint focus:border-accent-primary-dim/60 focus:shadow-[0_0_0_3px_oklch(0.75_0.15_128/0.08)] focus:outline-none"
			/>
		</div>
	</div>

	{#if loading}
		<div class="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
			{#each Array(6) as _}
				<Skeleton class="h-40 w-full" />
			{/each}
		</div>
	{:else if filtered.length === 0}
		<div class="border border-edge bg-surface-1 p-8 text-center text-[13px] text-fg-faint">
			No servers match the current filters.
		</div>
	{:else}
		<div class="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
			{#each filtered as entry (entry.name)}
				<div class="card-surface flex flex-col gap-3 p-4">
					<!-- Header -->
					<div class="flex items-start justify-between">
						<div>
							<h3 class="font-mono text-[14px] font-medium text-fg">{entry.display_name}</h3>
							<span
								class="rounded-full border border-edge px-2 py-0.5 text-[11px] capitalize text-fg-faint"
							>
								{entry.category}
							</span>
						</div>
						<span class="rounded-full border border-edge px-2 py-0.5 font-mono text-[11px] text-fg-faint">
							{entry.transport}
						</span>
					</div>

					<!-- Description -->
					<p class="text-[13px] leading-relaxed text-fg-muted">{entry.description}</p>

					<!-- Install hint -->
					<div class="mt-auto">
						<code
							class="block overflow-x-auto border border-edge-subtle bg-surface-05 px-3 py-2 font-mono text-[11px] text-fg-faint"
						>
							{entry.install_hint}
						</code>
					</div>

					<!-- Actions -->
					<div class="flex items-center gap-2">
						<button
							class="flex items-center gap-1 rounded-[2px] border border-edge px-2.5 py-1 text-[12px] text-fg-muted transition-colors hover:border-accent-primary-dim hover:text-fg"
							onclick={() => copyYaml(entry)}
						>
							{#if copiedName === entry.name}
								<Check size={12} />
								Copied
							{:else}
								<Copy size={12} />
								Add to Agent
							{/if}
						</button>
						{#if entry.homepage}
							<a
								href={entry.homepage}
								target="_blank"
								rel="noopener noreferrer"
								class="text-[12px] text-fg-faint transition-colors hover:text-accent-secondary"
							>
								Docs
							</a>
						{/if}
					</div>
				</div>
			{/each}
		</div>
	{/if}
</div>
