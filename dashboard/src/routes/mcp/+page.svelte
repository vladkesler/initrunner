<script lang="ts">
	import { onMount } from 'svelte';
	import { setCrumbs } from '$lib/stores/breadcrumb.svelte';
	import { listMcpServers } from '$lib/api/mcp';
	import type { McpServer } from '$lib/api/types';
	import { Skeleton } from '$lib/components/ui/skeleton';
	import { Tabs, TabsList, TabsTrigger, TabsContent } from '$lib/components/ui/tabs';
	import { Cable, Compass, Terminal, Network } from 'lucide-svelte';
	import McpServerList from '$lib/components/mcp/McpServerList.svelte';
	import McpDiscover from '$lib/components/mcp/McpDiscover.svelte';
	import McpPlayground from '$lib/components/mcp/McpPlayground.svelte';
	import McpCanvas from '$lib/components/mcp/McpCanvas.svelte';

	$effect(() => {
		setCrumbs([{ label: 'MCP Hub' }]);
	});

	let servers = $state<McpServer[]>([]);
	let loading = $state(true);
	let error = $state(false);

	const tabKey = 'mcp-hub-tab';
	let activeTab = $state('servers');

	function onTabChange(value: string | undefined) {
		if (!value) return;
		activeTab = value;
		try {
			localStorage.setItem(tabKey, value);
		} catch {
			/* ignore */
		}
	}

	onMount(async () => {
		try {
			const saved = localStorage.getItem(tabKey);
			if (saved && ['servers', 'discover', 'playground', 'canvas'].includes(saved)) {
				activeTab = saved;
			}
		} catch {
			/* ignore */
		}

		try {
			servers = await listMcpServers();
		} catch {
			error = true;
		} finally {
			loading = false;
		}
	});

	// Pre-selection state for playground (set by "Test" button in server cards)
	let playgroundServerId = $state<string | null>(null);
	let playgroundToolName = $state<string | null>(null);

	function openPlayground(serverId: string, toolName: string) {
		playgroundServerId = serverId;
		playgroundToolName = toolName;
		activeTab = 'playground';
		try {
			localStorage.setItem(tabKey, 'playground');
		} catch {
			/* ignore */
		}
	}
</script>

<div class="flex h-full flex-col gap-6 p-8">
	<!-- Header -->
	<div class="flex items-center gap-3">
		<h1 class="text-2xl font-semibold tracking-[-0.03em]">MCP Hub</h1>
		{#if !loading}
			<span
				class="rounded-full border border-edge bg-surface-1 px-2 py-0.5 font-mono text-[12px] text-fg-faint"
			>
				{servers.length} server{servers.length !== 1 ? 's' : ''}
			</span>
		{/if}
	</div>

	{#if loading}
		<div class="flex flex-col gap-3">
			<Skeleton class="h-10 w-full" />
			<Skeleton class="h-64 w-full" />
		</div>
	{:else if error}
		<div class="rounded-none border border-edge bg-surface-1 p-6 text-fg-muted">
			Failed to load MCP servers. Check that the API is running.
		</div>
	{:else}
		<Tabs value={activeTab} onValueChange={onTabChange} class="flex min-h-0 flex-1 flex-col">
			<TabsList
				variant="line"
				class="w-full justify-start gap-0 border-b border-edge bg-transparent px-0"
			>
				<TabsTrigger
					value="servers"
					class="gap-1.5 rounded-none border-b-2 border-transparent px-4 py-2.5 text-[13px] text-fg-faint transition-colors data-[state=active]:border-accent-primary-dim data-[state=active]:text-fg"
				>
					<Cable size={13} />
					Servers
				</TabsTrigger>
				<TabsTrigger
					value="discover"
					class="gap-1.5 rounded-none border-b-2 border-transparent px-4 py-2.5 text-[13px] text-fg-faint transition-colors data-[state=active]:border-accent-primary-dim data-[state=active]:text-fg"
				>
					<Compass size={13} />
					Discover
				</TabsTrigger>
				<TabsTrigger
					value="playground"
					class="gap-1.5 rounded-none border-b-2 border-transparent px-4 py-2.5 text-[13px] text-fg-faint transition-colors data-[state=active]:border-accent-primary-dim data-[state=active]:text-fg"
				>
					<Terminal size={13} />
					Playground
				</TabsTrigger>
				<TabsTrigger
					value="canvas"
					class="gap-1.5 rounded-none border-b-2 border-transparent px-4 py-2.5 text-[13px] text-fg-faint transition-colors data-[state=active]:border-accent-primary-dim data-[state=active]:text-fg"
				>
					<Network size={13} />
					Canvas
				</TabsTrigger>
			</TabsList>

			<TabsContent value="servers" class="min-h-0 flex-1 pt-4">
				<McpServerList {servers} {openPlayground} />
			</TabsContent>

			<TabsContent value="discover" class="min-h-0 flex-1 pt-4">
				<McpDiscover />
			</TabsContent>

			<TabsContent value="playground" class="min-h-0 flex-1 pt-4">
				<McpPlayground
					{servers}
					preSelectedServerId={playgroundServerId}
					preSelectedToolName={playgroundToolName}
				/>
			</TabsContent>

			<TabsContent value="canvas" class="min-h-0 flex-1 pt-4">
				<McpCanvas {servers} />
			</TabsContent>
		</Tabs>
	{/if}
</div>
