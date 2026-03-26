<script lang="ts">
	import type { HubSearchResult } from '$lib/api/builder';
	import { Skeleton } from '$lib/components/ui/skeleton';
	import HubResultCard from './HubResultCard.svelte';
	import { Search, Loader2, Info, ExternalLink } from 'lucide-svelte';

	let {
		hubQuery = $bindable(''),
		hubResults,
		hubSearching,
		hubError,
		selectedHubRef = $bindable(null),
		hubFeaturedResults,
		hubFeaturedLoading,
		onQueryInput,
		onSelectResult
	}: {
		hubQuery: string;
		hubResults: HubSearchResult[];
		hubSearching: boolean;
		hubError: string | null;
		selectedHubRef: string | null;
		hubFeaturedResults: HubSearchResult[];
		hubFeaturedLoading: boolean;
		onQueryInput: () => void;
		onSelectResult: (result: HubSearchResult) => void;
	} = $props();

	function refFor(result: HubSearchResult): string {
		return `${result.owner}/${result.name}@${result.latest_version || 'latest'}`;
	}
</script>

<div>
	<h2 class="mb-3 font-mono text-[12px] font-medium uppercase tracking-[0.1em] text-fg-faint">
		Search InitHub
	</h2>
	<div class="relative">
		<Search size={14} class="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-fg-faint" />
		<input
			type="text"
			bind:value={hubQuery}
			oninput={onQueryInput}
			placeholder="Search for agent packages..."
			class="w-full border border-edge bg-surface-1 py-2 pl-9 pr-3 font-mono text-[13px] text-fg outline-none transition-[border-color,box-shadow] duration-150 placeholder:text-fg-faint focus:border-accent-primary/40 focus:shadow-[0_0_0_3px_oklch(0.91_0.20_128/0.08)]"
		/>
	</div>

	<!-- Hub results -->
	<div class="mt-3">
		{#if hubSearching}
			<div class="flex items-center gap-2 py-6 justify-center text-fg-faint">
				<Loader2 size={14} class="animate-spin" />
				<span class="text-[13px]">Searching...</span>
			</div>
		{:else if hubError}
			<div class="border-l-2 border-l-fail bg-fail/5 px-3 py-2">
				<p class="text-[13px] text-fail">{hubError}</p>
			</div>
		{:else if hubQuery.trim().length >= 2 && hubResults.length === 0}
			<p class="py-6 text-center text-[13px] text-fg-faint">
				No packages found for '{hubQuery}'.
			</p>
		{:else if hubResults.length > 0}
			<div class="grid grid-cols-1 gap-2 sm:grid-cols-2">
				{#each hubResults as result}
					<HubResultCard
						{result}
						selected={selectedHubRef === refFor(result)}
						onSelect={onSelectResult}
					/>
				{/each}
			</div>
		{:else}
			<!-- Featured packages (shown when no search query) -->
			{#if hubFeaturedLoading}
				<div class="grid grid-cols-1 gap-2 sm:grid-cols-2">
					{#each Array(4) as _}
						<Skeleton class="h-24 bg-surface-1" />
					{/each}
				</div>
			{:else if hubFeaturedResults.length > 0}
				<div class="mb-2 flex items-center justify-between">
					<span class="font-mono text-[12px] font-medium uppercase tracking-[0.1em] text-fg-faint">
						Popular on InitHub
					</span>
					<a
						href="https://hub.initrunner.ai"
						target="_blank"
						rel="noopener"
						class="inline-flex items-center gap-1 text-[13px] text-accent-primary transition-[color] duration-150 hover:text-accent-primary-hover"
					>
						View all
						<ExternalLink size={12} />
					</a>
				</div>
				<div class="grid grid-cols-1 gap-2 sm:grid-cols-2">
					{#each hubFeaturedResults.slice(0, 8) as result, i}
						<HubResultCard
							{result}
							selected={selectedHubRef === refFor(result)}
							animationDelay="{i * 60}ms"
							onSelect={onSelectResult}
						/>
					{/each}
				</div>
			{:else}
				<p class="py-6 text-center text-[13px] text-fg-faint">
					Search for agent packages on InitHub
				</p>
			{/if}
		{/if}
	</div>

	<!-- CLI install hint -->
	<p class="mt-3 flex items-start gap-1.5 text-[12px] text-accent-primary/70">
		<Info size={12} class="mt-0.5 shrink-0" />
		<span>
			Dashboard loads the primary role YAML only. For complete packages with all bundled files, run
			<code class="font-mono text-accent-primary">initrunner install owner/name</code>.
		</span>
	</p>
</div>
