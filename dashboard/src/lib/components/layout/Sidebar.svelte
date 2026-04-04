<script lang="ts">
	import { page } from '$app/state';
	import { Compass, Blocks, Workflow, Users, Sparkles, Cable, ScanEye, Cpu, PanelLeftClose, PanelLeftOpen } from 'lucide-svelte';
	import { getMcpHealthSummary } from '$lib/api/mcp';
	import { onMount } from 'svelte';

	let { collapsed = false, onToggle }: { collapsed?: boolean; onToggle?: () => void } = $props();

	function isActive(href: string): boolean {
		if (href === '/') return page.url.pathname === '/';
		return page.url.pathname.startsWith(href);
	}

	const buildItems = [
		{ href: '/agents', label: 'Agents', icon: Blocks },
		{ href: '/flows', label: 'Flows', icon: Workflow },
		{ href: '/teams', label: 'Teams', icon: Users },
		{ href: '/skills', label: 'Skills', icon: Sparkles }
	];

	const operateItems = [
		{ href: '/mcp', label: 'MCP Hub', icon: Cable },
		{ href: '/audit', label: 'Audit', icon: ScanEye }
	];

	let mcpUnhealthy = $state(0);

	onMount(() => {
		const poll = () => {
			getMcpHealthSummary()
				.then((s) => { mcpUnhealthy = s.unhealthy; })
				.catch(() => { /* ignore */ });
		};
		poll();
		const id = setInterval(poll, 30_000);
		return () => clearInterval(id);
	});

	const homeActive = $derived(isActive('/'));
	const sysActive = $derived(isActive('/system'));
</script>

<nav
	class="relative flex h-full flex-col border-r border-edge bg-surface-05 transition-[width] duration-150"
	style="width: {collapsed ? '48px' : '220px'}"
>
	<!-- Zone 1: Brand -->
	<div class="flex h-12 items-center border-b border-edge-subtle px-3">
		{#if collapsed}
			<img src="/icon.svg" alt="InitRunner" class="mx-auto h-5 w-auto" />
		{:else}
			<img src="/logo.svg" alt="InitRunner" class="h-5 w-auto" />
		{/if}
	</div>

	<div class="flex flex-1 flex-col overflow-y-auto p-2">
		<!-- Launchpad (primary home) -->
		<a
			href="/"
			class="group mb-1 flex items-center gap-2.5 border-l-2 px-2.5 py-2.5 text-[13px] transition-[color,background-color,border-color] duration-150
				{homeActive
					? 'border-accent-primary text-fg'
					: 'border-transparent text-fg-faint hover:bg-gradient-to-r hover:from-accent-primary-wash hover:to-transparent hover:text-fg-muted'}"
			title={collapsed ? 'Launchpad' : undefined}
		>
			<Compass size={15} strokeWidth={1.5} />
			{#if !collapsed}
				<span>Launchpad</span>
			{/if}
		</a>

		<!-- Zone 2: Workspace -->
		{#if !collapsed}
			<div class="mb-1 mt-3 px-3 section-label" style="font-size: 10px; letter-spacing: 0.15em; opacity: 0.6">
				Build
			</div>
		{:else}
			<div class="my-2 border-t border-edge-subtle"></div>
		{/if}

		{#each buildItems as item}
			{@const active = isActive(item.href)}
			<a
				href={item.href}
				class="group flex items-center gap-2.5 border-l-2 px-2.5 py-2.5 text-[13px] transition-[color,background-color,border-color] duration-150
					{active
						? 'border-accent-primary text-fg'
						: 'border-transparent text-fg-faint hover:bg-gradient-to-r hover:from-accent-primary-wash hover:to-transparent hover:text-fg-muted'}"
				title={collapsed ? item.label : undefined}
			>
				<item.icon size={15} strokeWidth={1.5} />
				{#if !collapsed}
					<span>{item.label}</span>
				{/if}
			</a>
		{/each}

		{#if !collapsed}
			<div class="mb-1 mt-4 px-3 section-label" style="font-size: 10px; letter-spacing: 0.15em; opacity: 0.6">
				Operate
			</div>
		{:else}
			<div class="my-2 border-t border-edge-subtle"></div>
		{/if}

		{#each operateItems as item}
			{@const active = isActive(item.href)}
			<a
				href={item.href}
				class="group relative flex items-center gap-2.5 border-l-2 px-2.5 py-2.5 text-[13px] transition-[color,background-color,border-color] duration-150
					{active
						? 'border-accent-primary text-fg'
						: 'border-transparent text-fg-faint hover:bg-gradient-to-r hover:from-accent-primary-wash hover:to-transparent hover:text-fg-muted'}"
				title={collapsed ? item.label : undefined}
			>
				<item.icon size={15} strokeWidth={1.5} />
				{#if !collapsed}
					<span>{item.label}</span>
				{/if}
				{#if item.href === '/mcp' && mcpUnhealthy > 0}
					<span class="status-dot absolute right-2 top-1/2 -translate-y-1/2" style="background: var(--color-fail)"></span>
				{/if}
			</a>
		{/each}
	</div>

	<!-- Zone 3: Meta (bottom) -->
	<div class="border-t border-edge-subtle p-2">
		<a
			href="/system"
			class="group flex items-center gap-2.5 border-l-2 px-2.5 py-2.5 text-[13px] transition-[color,background-color,border-color] duration-150
				{sysActive
					? 'border-accent-primary text-fg'
					: 'border-transparent text-fg-faint hover:bg-gradient-to-r hover:from-accent-primary-wash hover:to-transparent hover:text-fg-muted'}"
			title={collapsed ? 'System' : undefined}
		>
			<Cpu size={15} strokeWidth={1.5} />
			{#if !collapsed}
				<span>System</span>
			{/if}
		</a>

		<button
			class="mt-1 flex w-full items-center justify-center py-1.5 text-fg-faint transition-[color] duration-150 hover:text-fg-muted"
			onclick={onToggle}
			aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
		>
			{#if collapsed}
				<PanelLeftOpen size={14} />
			{:else}
				<PanelLeftClose size={14} />
			{/if}
		</button>
	</div>
</nav>
