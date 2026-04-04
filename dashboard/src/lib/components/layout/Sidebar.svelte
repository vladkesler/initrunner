<script lang="ts">
	import { page } from '$app/state';
	import { onMount } from 'svelte';
	import { Compass, Blocks, Sparkles, Workflow, Users, ScanEye, Cpu, Network, ChevronRight, PanelLeftClose, PanelLeftOpen } from 'lucide-svelte';
	import { safeGet, safeSet } from '$lib/utils/storage';

	let { collapsed = false, onToggle }: { collapsed?: boolean; onToggle?: () => void } = $props();

	function isActive(href: string): boolean {
		if (href === '/') return page.url.pathname === '/';
		return page.url.pathname.startsWith(href);
	}

	const topItems = [
		{ href: '/', label: 'Launchpad', icon: Compass },
		{ href: '/agents', label: 'Agents', icon: Blocks }
	];
	const orchChildren = [
		{ href: '/flows', label: 'Flows', icon: Workflow },
		{ href: '/teams', label: 'Teams', icon: Users }
	];
	const midItems = [
		{ href: '/skills', label: 'Skills', icon: Sparkles }
	];
	const bottomItems = [
		{ href: '/audit', label: 'Audit', icon: ScanEye },
		{ href: '/system', label: 'System', icon: Cpu }
	];

	let orchestrationOpen = $state(false);
	let flyoutOpen = $state(false);

	onMount(() => {
		if (safeGet('sidebar-orch-open') === 'true') orchestrationOpen = true;
	});

	const orchChildActive = $derived(
		page.url.pathname.startsWith('/flows') || page.url.pathname.startsWith('/teams')
	);

	$effect(() => {
		if (orchChildActive) orchestrationOpen = true;
	});

	function toggleOrchestration() {
		if (orchChildActive) return;
		orchestrationOpen = !orchestrationOpen;
		safeSet('sidebar-orch-open', String(orchestrationOpen));
	}

	function handleFlyoutBlur(e: FocusEvent) {
		const container = (e.currentTarget as HTMLElement).closest('[role="group"]');
		if (!container?.contains(e.relatedTarget as Node)) {
			flyoutOpen = false;
		}
	}
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
			<img src="/icon.svg" alt="InitRunner" class="mx-auto h-5 w-auto" />
		{:else}
			<img src="/logo.svg" alt="InitRunner" class="h-5 w-auto" />
		{/if}
	</div>

	<!-- Navigation -->
	<div class="flex flex-1 flex-col gap-1 p-2">
		<!-- Top items: Launchpad, Agents -->
		{#each topItems as item}
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

		<!-- Orchestration group -->
		{#if collapsed}
			<!-- Collapsed: flyout variant -->
			<div
				class="relative"
				role="group"
				onmouseenter={() => (flyoutOpen = true)}
				onmouseleave={() => (flyoutOpen = false)}
			>
				<button
					class="group flex w-full items-center justify-center px-2.5 py-2 text-[13px] transition-[color,background-color] duration-150 {orchChildActive ? 'bg-accent-primary/10 text-accent-primary' : 'text-fg-faint hover:bg-surface-2 hover:text-fg-muted'}"
					onfocus={() => (flyoutOpen = true)}
					onblur={handleFlyoutBlur}
					aria-expanded={flyoutOpen}
					aria-label="Orchestration"
				>
					<Network size={15} strokeWidth={1.5} />
				</button>

				{#if flyoutOpen}
					<div class="absolute left-full top-0 z-10 ml-1 min-w-[160px] border border-edge bg-surface-1 py-1 shadow-lg">
						<div class="px-3 py-1.5 font-mono text-[11px] font-medium uppercase tracking-[0.12em] text-fg-faint">
							Orchestration
						</div>
						{#each orchChildren as child}
							{@const active = isActive(child.href)}
							<a
								href={child.href}
								class="flex items-center gap-2.5 px-3 py-2 text-[13px] transition-[color,background-color] duration-150 {active ? 'bg-accent-primary/10 text-accent-primary' : 'text-fg-muted hover:bg-surface-2 hover:text-fg'}"
								onfocus={() => (flyoutOpen = true)}
								onblur={handleFlyoutBlur}
							>
								<child.icon size={15} strokeWidth={1.5} />
								<span class="font-mono">{child.label}</span>
							</a>
						{/each}
					</div>
				{/if}
			</div>
		{:else}
			<!-- Expanded: group header + children -->
			<button
				class="group flex w-full items-center gap-2.5 px-2.5 py-2 text-[13px] transition-[color,background-color] duration-150 {orchChildActive ? 'text-accent-primary' : 'text-fg-faint hover:bg-surface-2 hover:text-fg-muted'}"
				onclick={toggleOrchestration}
				aria-expanded={orchestrationOpen}
			>
				<Network size={15} strokeWidth={1.5} />
				<span class="font-mono">Orchestration</span>
				<ChevronRight
					size={12}
					strokeWidth={1.5}
					class="ml-auto transition-transform duration-150 {orchestrationOpen ? 'rotate-90' : ''}"
				/>
			</button>

			{#if orchestrationOpen}
				<div class="ml-3">
					{#each orchChildren as child}
						{@const active = isActive(child.href)}
						<a
							href={child.href}
							class="group flex items-center gap-2.5 px-2.5 py-2 text-[13px] transition-[color,background-color] duration-150 {active ? 'bg-accent-primary/10 text-accent-primary' : 'text-fg-faint hover:bg-surface-2 hover:text-fg-muted'}"
						>
							<child.icon size={15} strokeWidth={1.5} />
							<span class="font-mono">{child.label}</span>
						</a>
					{/each}
				</div>
			{/if}
		{/if}

		<!-- Skills (below Orchestration) -->
		{#each midItems as item}
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

		<!-- Bottom items: Audit, System -->
		{#each bottomItems as item}
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
