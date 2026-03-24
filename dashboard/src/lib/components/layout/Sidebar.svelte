<script lang="ts">
	import { page } from '$app/state';
	import { Compass, Blocks, Workflow, ScanEye, Cpu, PanelLeftClose, PanelLeftOpen } from 'lucide-svelte';

	let { collapsed = false, onToggle }: { collapsed?: boolean; onToggle?: () => void } = $props();

	function isActive(href: string): boolean {
		if (href === '/') return page.url.pathname === '/';
		return page.url.pathname.startsWith(href);
	}

	const navItems = [
		{ href: '/', label: 'Launchpad', icon: Compass },
		{ href: '/agents', label: 'Agents', icon: Blocks },
		{ href: '/compose', label: 'Compose', icon: Workflow },
		{ href: '/audit', label: 'Audit', icon: ScanEye },
		{ href: '/system', label: 'System', icon: Cpu }
	];
</script>

<nav
	class="relative flex h-full flex-col border-r border-edge bg-[#111113] transition-[width] duration-150"
	style="width: {collapsed ? '48px' : '200px'}"
>
	<!-- Lime gradient highlight on right edge -->
	<div class="pointer-events-none absolute right-0 top-0 h-24 w-px bg-gradient-to-b from-accent-primary/15 via-transparent to-transparent"></div>

	<!-- Logo -->
	<div class="flex h-12 items-center border-b border-edge px-3">
		{#if collapsed}
			<span class="w-full text-center font-mono text-sm font-medium text-accent-primary">></span>
		{:else}
			<span class="font-mono text-sm font-medium uppercase tracking-[0.08em] text-fg-faint"><span class="text-accent-primary">></span> InitRunner</span>
		{/if}
	</div>

	<!-- Navigation -->
	<div class="flex flex-1 flex-col gap-1 p-2">
		{#each navItems as item}
			{@const active = isActive(item.href)}
			<a
				href={item.href}
				class="group flex items-center gap-2.5 px-2.5 py-2 text-[13px] transition-[color,background-color] duration-150 {active ? 'bg-accent-primary/10 text-accent-primary' : 'text-fg-faint hover:bg-surface-2 hover:text-fg-muted'}"
				title={collapsed ? item.label : undefined}
			>
				<item.icon size={15} strokeWidth={1.5} />
				{#if !collapsed}
					<span class="font-mono">{item.label}</span>
				{/if}
			</a>
		{/each}
	</div>

	<!-- Collapse toggle -->
	<div class="border-t border-edge p-2">
		<button
			class="flex w-full items-center justify-center py-1.5 text-fg-faint transition-[color,background-color] duration-150 hover:bg-surface-2 hover:text-fg-muted"
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
