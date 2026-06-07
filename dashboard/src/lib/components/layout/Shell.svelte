<script lang="ts">
	import { onMount } from 'svelte';
	import Sidebar from './Sidebar.svelte';
	import HeaderBar from './HeaderBar.svelte';
	import CommandPalette from './CommandPalette.svelte';
	import { safeGet, safeSet } from '$lib/utils/storage';
	import { needsConsentPrompt, setConsent } from '$lib/telemetry';

	let { children }: { children: any } = $props();
	let collapsed = $state(false);
	let showTelemetryConsent = $state(false);

	onMount(() => {
		const stored = safeGet('sidebar-collapsed');
		if (stored === 'true') collapsed = true;
		showTelemetryConsent = needsConsentPrompt();
	});

	function enableTelemetry() {
		setConsent(true);
		showTelemetryConsent = false;
	}

	function declineTelemetry() {
		setConsent(false);
		showTelemetryConsent = false;
	}

	function toggleSidebar() {
		collapsed = !collapsed;
		safeSet('sidebar-collapsed', String(collapsed));
	}

	function handleKeydown(e: KeyboardEvent) {
		if ((e.metaKey || e.ctrlKey) && e.key === 'b') {
			e.preventDefault();
			toggleSidebar();
		}
	}
</script>

<svelte:window onkeydown={handleKeydown} />

<div class="flex h-dvh overflow-hidden bg-background">
	<Sidebar {collapsed} onToggle={toggleSidebar} />
	<div class="flex min-w-0 flex-1 flex-col overflow-hidden">
		<HeaderBar />
		{#if showTelemetryConsent}
			<div
				class="flex flex-wrap items-center gap-3 border-b border-border bg-muted/40 px-8 py-2 text-sm text-muted-foreground lg:px-10"
			>
				<span class="min-w-0 flex-1">
					Help improve InitRunner? Send anonymous usage data (pages visited; no inputs or
					content) to guide what to build next. Nothing is sent until you choose.
				</span>
				<button
					class="rounded-md px-3 py-1 text-foreground hover:bg-muted"
					onclick={declineTelemetry}
				>
					No thanks
				</button>
				<button
					class="rounded-md bg-primary px-3 py-1 text-primary-foreground hover:bg-primary/90"
					onclick={enableTelemetry}
				>
					Enable
				</button>
			</div>
		{/if}
		<main class="min-w-0 flex-1 overflow-auto px-8 py-6 lg:px-10">
			<div class="mx-auto max-w-[1400px]">
				{@render children()}
			</div>
		</main>
	</div>
</div>

<CommandPalette />
