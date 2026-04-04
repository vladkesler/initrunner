<script lang="ts">
	import { page } from '$app/state';
	import { onMount } from 'svelte';
	import { Search } from 'lucide-svelte';
	import { getCrumbs } from '$lib/stores/breadcrumb.svelte';
	import { togglePalette } from '$lib/stores/command-palette.svelte';
	import { request } from '$lib/api/client';
	import type { HealthStatus } from '$lib/api/types';

	let healthy = $state<boolean | null>(null);

	const crumbs = $derived(getCrumbs());

	// Derive fallback crumbs from pathname when store is empty
	const displayCrumbs = $derived.by(() => {
		if (crumbs.length > 0) return crumbs;
		const segments = page.url.pathname.split('/').filter(Boolean);
		if (segments.length === 0) return [{ label: 'Launchpad' }];
		return segments.map((seg, i) => {
			// Skip raw IDs (UUIDs or numeric)
			if (/^[0-9a-f-]{8,}$/i.test(seg) || /^\d+$/.test(seg)) return null;
			const label = seg.charAt(0).toUpperCase() + seg.slice(1).replace(/-/g, ' ');
			const isLast = i === segments.length - 1 || (i === segments.length - 2 && /^[0-9a-f-]{8,}$/i.test(segments[i + 1]));
			if (isLast) return { label };
			return { label, href: '/' + segments.slice(0, i + 1).join('/') };
		}).filter((c): c is { label: string; href?: string } => c !== null);
	});

	const isMac = $derived(typeof navigator !== 'undefined' && /Mac|iPhone/.test(navigator.userAgent));

	onMount(async () => {
		try {
			const h = await request<HealthStatus>('/api/health');
			healthy = h.status === 'ok';
		} catch {
			healthy = false;
		}
	});
</script>

<header class="flex h-12 shrink-0 items-center justify-between border-b border-edge bg-surface-0 px-6">
	<!-- Breadcrumbs -->
	<nav class="flex items-center gap-1.5 text-[13px]" aria-label="Breadcrumb">
		{#each displayCrumbs as crumb, i}
			{#if i > 0}
				<span class="text-fg-faint/30">/</span>
			{/if}
			{#if crumb.href}
				<a
					href={crumb.href}
					class="text-fg-faint transition-[color] duration-150 hover:text-fg-muted"
				>{crumb.label}</a>
			{:else}
				<span class="text-fg">{crumb.label}</span>
			{/if}
		{/each}
	</nav>

	<!-- Right: search trigger + health -->
	<div class="flex items-center gap-3">
		<button
			class="flex items-center gap-2.5 rounded-[2px] border border-edge bg-surface-1 px-3 py-1.5 text-[13px] text-fg-faint transition-[color,border-color] duration-150 hover:border-accent-primary-dim/40 hover:text-fg-muted"
			onclick={togglePalette}
		>
			<Search size={14} strokeWidth={1.5} />
			<span>Search...</span>
			<kbd class="ml-2 rounded-[2px] border border-edge bg-surface-2 px-1.5 py-0.5 font-mono text-[11px] text-fg-faint">
				{isMac ? '⌘' : 'Ctrl'}K
			</kbd>
		</button>

		{#if healthy !== null}
			<a
				href="/system"
				class="flex items-center gap-1.5"
				title={healthy ? 'System healthy' : 'System degraded'}
			>
				<span
					class="status-dot"
					class:bg-ok={healthy}
					class:bg-warn={!healthy}
				></span>
			</a>
		{/if}
	</div>
</header>
