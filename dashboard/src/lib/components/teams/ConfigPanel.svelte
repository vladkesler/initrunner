<script lang="ts">
	import type { TeamDetail } from '$lib/api/types';
	import { ChevronRight, Database, FileText, Eye, EyeOff, Wrench } from 'lucide-svelte';

	let { team }: { team: TeamDetail } = $props();

	let sections = $state({
		model: true,
		strategy: true,
		guardrails: false,
		sharedMemory: false,
		sharedDocuments: false,
		tools: false,
		observability: false
	});

	function toggle(key: keyof typeof sections) {
		sections[key] = !sections[key];
	}

	const memoryEnabled = $derived(
		team.shared_memory && (team.shared_memory as Record<string, unknown>).enabled === true
	);
	const documentsEnabled = $derived(
		team.shared_documents && (team.shared_documents as Record<string, unknown>).enabled === true
	);
	const observabilityEnabled = $derived(
		team.observability && (team.observability as Record<string, unknown>).enabled === true
	);

	const guardrailEntries = $derived(
		Object.entries(team.guardrails as Record<string, unknown>)
	);

	const mem = $derived(team.shared_memory as Record<string, unknown>);
	const docs = $derived(team.shared_documents as Record<string, unknown>);
	const docSources = $derived(
		documentsEnabled && docs.sources ? (docs.sources as string[]) : []
	);
</script>

<div class="space-y-1">
	<!-- Model -->
	<div>
		<button
			class="flex w-full items-center gap-1.5 py-1.5 text-left"
			onclick={() => toggle('model')}
			aria-expanded={sections.model}
		>
			<ChevronRight
				size={12}
				class="shrink-0 text-fg-faint transition-transform duration-150 {sections.model ? 'rotate-90' : ''}"
			/>
			<span class="font-mono text-[12px] font-medium uppercase tracking-[0.1em] text-fg-faint">Model</span>
		</button>
		{#if sections.model}
			<div class="pb-3 pl-[18px] pt-1">
				<div class="grid grid-cols-2 gap-x-4 gap-y-1 font-mono text-[12px]">
					<span class="text-fg-faint">provider</span>
					<span class="text-fg-muted">{(team.model as Record<string, unknown>).provider ?? '-'}</span>
					<span class="text-fg-faint">model</span>
					<span class="text-fg-muted">{(team.model as Record<string, unknown>).name ?? '-'}</span>
				</div>
			</div>
		{/if}
	</div>

	<!-- Strategy -->
	<div>
		<button
			class="flex w-full items-center gap-1.5 py-1.5 text-left"
			onclick={() => toggle('strategy')}
			aria-expanded={sections.strategy}
		>
			<ChevronRight
				size={12}
				class="shrink-0 text-fg-faint transition-transform duration-150 {sections.strategy ? 'rotate-90' : ''}"
			/>
			<span class="font-mono text-[12px] font-medium uppercase tracking-[0.1em] text-fg-faint">Strategy</span>
		</button>
		{#if sections.strategy}
			<div class="pb-3 pl-[18px] pt-1">
				<div class="grid grid-cols-2 gap-x-4 gap-y-1 font-mono text-[12px]">
					<span class="text-fg-faint">strategy</span>
					<span class="text-fg-muted">{team.strategy}</span>
					<span class="text-fg-faint">handoff_max_chars</span>
					<span class="tabular-nums text-fg-muted">{team.handoff_max_chars.toLocaleString()}</span>
				</div>
			</div>
		{/if}
	</div>

	<!-- Guardrails -->
	<div>
		<button
			class="flex w-full items-center gap-1.5 py-1.5 text-left"
			onclick={() => toggle('guardrails')}
			aria-expanded={sections.guardrails}
		>
			<ChevronRight
				size={12}
				class="shrink-0 text-fg-faint transition-transform duration-150 {sections.guardrails ? 'rotate-90' : ''}"
			/>
			<span class="font-mono text-[12px] font-medium uppercase tracking-[0.1em] text-fg-faint">Guardrails</span>
		</button>
		{#if sections.guardrails}
			<div class="pb-3 pl-[18px] pt-1">
				<div class="space-y-2 text-[12px]">
					{#each guardrailEntries as [key, value]}
						<div class="grid grid-cols-2 gap-x-4 font-mono">
							<span class="text-fg-faint">{key}</span>
							<span class="tabular-nums text-fg-muted">
								{typeof value === 'object' ? JSON.stringify(value) : String(value)}
							</span>
						</div>
					{/each}
					{#if guardrailEntries.length === 0}
						<span class="font-mono text-fg-faint">No guardrails configured</span>
					{/if}
				</div>
			</div>
		{/if}
	</div>

	<!-- Shared Memory -->
	<div>
		<button
			class="flex w-full items-center gap-1.5 py-1.5 text-left"
			onclick={() => toggle('sharedMemory')}
			aria-expanded={sections.sharedMemory}
		>
			<ChevronRight
				size={12}
				class="shrink-0 text-fg-faint transition-transform duration-150 {sections.sharedMemory ? 'rotate-90' : ''}"
			/>
			<span class="font-mono text-[12px] font-medium uppercase tracking-[0.1em] text-fg-faint">Shared Memory</span>
		</button>
		{#if sections.sharedMemory}
			<div class="pb-3 pl-[18px] pt-1">
				<div class="space-y-2 text-[12px]">
					<div class="flex items-center gap-2">
						<Database size={11} class="text-fg-faint" />
						{#if memoryEnabled}
							<span class="rounded-full border border-ok/20 bg-ok/10 px-2 py-0.5 font-mono text-[11px] text-ok">enabled</span>
						{:else}
							<span class="rounded-full border border-edge bg-surface-2 px-2 py-0.5 font-mono text-[11px] text-fg-faint">disabled</span>
						{/if}
					</div>
					{#if memoryEnabled}
						<div class="grid grid-cols-2 gap-x-4 gap-y-1 font-mono">
							{#if mem.max_memories !== undefined}
								<span class="text-fg-faint">max_memories</span>
								<span class="tabular-nums text-fg-muted">{mem.max_memories}</span>
							{/if}
							{#if mem.store_path}
								<span class="text-fg-faint">store_path</span>
								<span class="text-fg-muted">{mem.store_path}</span>
							{/if}
						</div>
					{/if}
				</div>
			</div>
		{/if}
	</div>

	<!-- Shared Documents -->
	<div>
		<button
			class="flex w-full items-center gap-1.5 py-1.5 text-left"
			onclick={() => toggle('sharedDocuments')}
			aria-expanded={sections.sharedDocuments}
		>
			<ChevronRight
				size={12}
				class="shrink-0 text-fg-faint transition-transform duration-150 {sections.sharedDocuments ? 'rotate-90' : ''}"
			/>
			<span class="font-mono text-[12px] font-medium uppercase tracking-[0.1em] text-fg-faint">Shared Documents</span>
		</button>
		{#if sections.sharedDocuments}
			<div class="pb-3 pl-[18px] pt-1">
				<div class="space-y-2 text-[12px]">
					<div class="flex items-center gap-2">
						<FileText size={11} class="text-fg-faint" />
						{#if documentsEnabled}
							<span class="rounded-full border border-ok/20 bg-ok/10 px-2 py-0.5 font-mono text-[11px] text-ok">enabled</span>
						{:else}
							<span class="rounded-full border border-edge bg-surface-2 px-2 py-0.5 font-mono text-[11px] text-fg-faint">disabled</span>
						{/if}
					</div>
					{#if docSources.length > 0}
						<div class="space-y-1 font-mono text-[11px]">
							{#each docSources as src}
								<div class="text-fg-muted">{src}</div>
							{/each}
						</div>
					{/if}
				</div>
			</div>
		{/if}
	</div>

	<!-- Tools -->
	{#if team.tools.length > 0}
		<div>
			<button
				class="flex w-full items-center gap-1.5 py-1.5 text-left"
				onclick={() => toggle('tools')}
				aria-expanded={sections.tools}
			>
				<ChevronRight
					size={12}
					class="shrink-0 text-fg-faint transition-transform duration-150 {sections.tools ? 'rotate-90' : ''}"
				/>
				<span class="font-mono text-[12px] font-medium uppercase tracking-[0.1em] text-fg-faint">
					Tools
				</span>
				<span class="font-mono text-[12px] text-fg-faint">({team.tools.length})</span>
			</button>
			{#if sections.tools}
				<div class="pb-3 pl-[18px] pt-1">
					<div class="space-y-1.5">
						{#each team.tools as tool}
							<div class="flex items-center gap-2 text-[12px]">
								<Wrench size={11} class="shrink-0 text-fg-faint" />
								<span class="font-mono font-medium text-fg-muted">{tool.type}</span>
								{#if tool.summary}
									<span class="text-fg-faint">{tool.summary}</span>
								{/if}
							</div>
						{/each}
					</div>
				</div>
			{/if}
		</div>
	{/if}

	<!-- Observability -->
	<div>
		<button
			class="flex w-full items-center gap-1.5 py-1.5 text-left"
			onclick={() => toggle('observability')}
			aria-expanded={sections.observability}
		>
			<ChevronRight
				size={12}
				class="shrink-0 text-fg-faint transition-transform duration-150 {sections.observability ? 'rotate-90' : ''}"
			/>
			<span class="font-mono text-[12px] font-medium uppercase tracking-[0.1em] text-fg-faint">Observability</span>
		</button>
		{#if sections.observability}
			<div class="pb-3 pl-[18px] pt-1">
				<div class="flex items-center gap-2 text-[12px]">
					{#if observabilityEnabled}
						<Eye size={11} class="text-fg-faint" />
						<span class="rounded-full border border-ok/20 bg-ok/10 px-2 py-0.5 font-mono text-[11px] text-ok">enabled</span>
					{:else}
						<EyeOff size={11} class="text-fg-faint" />
						<span class="rounded-full border border-edge bg-surface-2 px-2 py-0.5 font-mono text-[11px] text-fg-faint">disabled</span>
					{/if}
				</div>
			</div>
		{/if}
	</div>
</div>
