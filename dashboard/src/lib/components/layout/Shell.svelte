<script lang="ts">
	import { onMount } from 'svelte';
	import Sidebar from './Sidebar.svelte';
	import HeaderBar from './HeaderBar.svelte';
	import CommandPalette from './CommandPalette.svelte';
	import { safeGet, safeSet } from '$lib/utils/storage';

	let { children }: { children: any } = $props();
	let collapsed = $state(false);

	onMount(() => {
		const stored = safeGet('sidebar-collapsed');
		if (stored === 'true') collapsed = true;
	});

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
		<main class="min-w-0 flex-1 overflow-auto px-8 py-6 lg:px-10">
			<div class="mx-auto max-w-[1400px]">
				{@render children()}
			</div>
		</main>
	</div>
</div>

<CommandPalette />
