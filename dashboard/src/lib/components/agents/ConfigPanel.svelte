<script lang="ts">
	import type { AgentDetail } from '$lib/api/types';
	import ConfigSection from './ConfigSection.svelte';
	import { Copy, Check, ExternalLink } from 'lucide-svelte';

	let { detail, yaml = '' }: { detail: AgentDetail; yaml?: string } = $props();

	let copied = $state(false);

	const model = $derived(detail.model as { provider?: string; name?: string; temperature?: number; max_tokens?: number });
	const guardrails = $derived(detail.guardrails as {
		max_tokens_per_run?: number;
		max_tool_calls?: number;
		timeout_seconds?: number;
		max_iterations?: number;
	});
	const memory = $derived(detail.memory as {
		episodic?: { enabled?: boolean };
		semantic?: { enabled?: boolean };
		procedural?: { enabled?: boolean };
		max_sessions?: number;
	} | null);
	const ingest = $derived(detail.ingest as {
		sources?: string[];
		watch?: boolean;
		chunking?: { strategy?: string; chunk_size?: number };
	} | null);
	const reasoning = $derived(detail.reasoning as {
		pattern?: string;
		auto_plan?: boolean;
		reflection_rounds?: number;
		reflection_dimensions?: Array<{ name: string; prompt: string }> | null;
		auto_detect?: boolean;
	} | null);
	const autonomy = $derived(detail.autonomy as {
		max_plan_steps?: number;
		max_history_messages?: number;
		iteration_delay_seconds?: number;
		compaction?: { enabled?: boolean; threshold?: number; tail_messages?: number };
	} | null);
	const thinkTool = $derived(detail.tools.find((t) => t.type === 'think'));
	const todoTool = $derived(detail.tools.find((t) => t.type === 'todo'));
	const hasCognition = $derived(reasoning || autonomy || thinkTool || todoTool);

	async function copyYaml() {
		await navigator.clipboard.writeText(yaml);
		copied = true;
		setTimeout(() => (copied = false), 2000);
	}
</script>

<div class="space-y-1">
	<!-- Model (always visible, not collapsible) -->
	<div class="pb-3">
		<h3 class="mb-2 section-label">
			Model
		</h3>
		<div class="pl-0.5 font-mono text-[13px]">
			<span class="text-fg-muted">{model.provider || 'unknown'}</span>
			<span class="text-fg-faint">/</span>
			<span class="text-fg-muted">{model.name || 'unknown'}</span>
		</div>
		<div class="mt-1 flex gap-4 pl-0.5 font-mono text-[13px]" style="font-variant-numeric: tabular-nums">
			<span><span class="text-fg-faint">temp</span> <span class="text-fg-muted">{model.temperature ?? 0.1}</span></span>
			<span><span class="text-fg-faint">max</span> <span class="text-fg-muted">{(model.max_tokens ?? 4096).toLocaleString()}</span></span>
		</div>
	</div>

	<!-- Tools -->
	{#if detail.tools.length > 0}
		<ConfigSection title="Tools" count={detail.tools.length}>
			<div class="space-y-1">
				{#each detail.tools as tool}
					<div class="font-mono text-[13px]">
						<span class="text-accent-primary">{tool.type}</span>
						<span class="ml-1.5 text-fg-muted">{tool.summary}</span>
					</div>
				{/each}
			</div>
		</ConfigSection>
	{/if}

	<!-- Capabilities -->
	{#if detail.capabilities.length > 0}
		<ConfigSection title="Capabilities" count={detail.capabilities.length}>
			<div class="space-y-1">
				{#each detail.capabilities as cap}
					<div class="font-mono text-[13px]">
						<span class="text-accent-secondary">{cap.type}</span>
						<span class="ml-1.5 text-fg-muted">{cap.summary}</span>
					</div>
				{/each}
			</div>
		</ConfigSection>
	{/if}

	<!-- Triggers -->
	{#if detail.triggers.length > 0}
		<ConfigSection title="Triggers" count={detail.triggers.length}>
			<div class="space-y-1">
				{#each detail.triggers as trigger}
					<div class="font-mono text-[13px]">
						<span class="text-accent-secondary">{trigger.type}</span>
						<span class="ml-1.5 text-fg-muted">{trigger.summary}</span>
					</div>
				{/each}
			</div>
		</ConfigSection>
	{/if}

	<!-- Guardrails (always visible) -->
	<ConfigSection title="Guardrails">
		<div class="grid grid-cols-2 gap-x-4 gap-y-1 font-mono text-[13px]" style="font-variant-numeric: tabular-nums">
			<div>
				<span class="text-fg-faint">max tokens</span>
				<span class="ml-1 text-fg-muted">{(guardrails.max_tokens_per_run ?? 50000).toLocaleString()}</span>
			</div>
			<div>
				<span class="text-fg-faint">timeout</span>
				<span class="ml-1 text-fg-muted">{guardrails.timeout_seconds ?? 300}s</span>
			</div>
			<div>
				<span class="text-fg-faint">tool calls</span>
				<span class="ml-1 text-fg-muted">{guardrails.max_tool_calls ?? 20}</span>
			</div>
			<div>
				<span class="text-fg-faint">iterations</span>
				<span class="ml-1 text-fg-muted">{guardrails.max_iterations ?? 10}</span>
			</div>
		</div>
	</ConfigSection>

	<!-- Tool Search -->
	{#if detail.tool_search}
		<ConfigSection title="Tool Search">
			<div class="space-y-1 font-mono text-[13px]" style="font-variant-numeric: tabular-nums">
				<div>
					<span class="text-fg-faint">status</span>
					<span class="ml-1 text-status-ok">active</span>
				</div>
				{#if detail.tool_search.always_available.length > 0}
					<div>
						<span class="text-fg-faint">always visible</span>
						<span class="ml-1 text-fg-muted">{detail.tool_search.always_available.join(', ')}</span>
					</div>
				{/if}
				<div>
					<span class="text-fg-faint">discoverable</span>
					<span class="ml-1 text-fg-muted">{detail.tools.length - detail.tool_search.always_available.length} tools via search</span>
				</div>
				<div>
					<span class="text-fg-faint">max results</span>
					<span class="ml-1 text-fg-muted">{detail.tool_search.max_results}</span>
				</div>
			</div>
		</ConfigSection>
	{/if}

	<!-- Memory -->
	{#if memory}
		<ConfigSection title="Memory">
			<div class="flex flex-wrap gap-3 font-mono text-[13px]">
				<span class={memory.episodic?.enabled ? 'text-fg-muted' : 'text-fg-faint line-through'}>episodic</span>
				<span class={memory.semantic?.enabled ? 'text-fg-muted' : 'text-fg-faint line-through'}>semantic</span>
				<span class={memory.procedural?.enabled ? 'text-fg-muted' : 'text-fg-faint line-through'}>procedural</span>
			</div>
			{#if memory.max_sessions}
				<div class="mt-1 font-mono text-[13px]">
					<span class="text-fg-faint">max sessions</span>
					<span class="ml-1 text-fg-muted">{memory.max_sessions}</span>
				</div>
			{/if}
		</ConfigSection>
	{/if}

	<!-- Ingestion -->
	{#if ingest}
		<ConfigSection title="Ingestion">
			<div class="space-y-1 font-mono text-[13px]">
				{#if ingest.sources}
					<div>
						<span class="text-fg-faint">sources</span>
						<span class="ml-1 text-fg-muted">{ingest.sources.join(', ')}</span>
					</div>
				{/if}
				{#if ingest.chunking}
					<div>
						<span class="text-fg-faint">chunking</span>
						<span class="ml-1 text-fg-muted">{ingest.chunking.strategy} / {ingest.chunking.chunk_size}</span>
					</div>
				{/if}
				<div>
					<span class="text-fg-faint">watch</span>
					<span class="ml-1 text-fg-muted">{ingest.watch ? 'on' : 'off'}</span>
				</div>
			</div>
		</ConfigSection>
	{/if}

	<!-- Skills -->
	{#if detail.skill_refs && detail.skill_refs.length > 0}
		<ConfigSection title="Skills" count={detail.skill_refs.length}>
			<div class="flex flex-wrap gap-1.5">
				{#each detail.skill_refs as ref}
					{#if ref.skill_id}
						<a
							href="/skills/{ref.skill_id}"
							class="font-mono text-[13px] text-accent-primary transition-[color] duration-150 hover:underline"
						>
							{ref.name}
						</a>
					{:else}
						<a
							href="/skills?search={encodeURIComponent(ref.name)}"
							class="font-mono text-[13px] text-fg-muted transition-[color] duration-150 hover:text-accent-primary hover:underline"
							title="Could not resolve to a specific skill"
						>
							{ref.name}
						</a>
					{/if}
				{/each}
			</div>
		</ConfigSection>
	{:else if detail.skills.length > 0}
		<ConfigSection title="Skills" count={detail.skills.length}>
			<div class="flex flex-wrap gap-1.5">
				{#each detail.skills as skill}
					<a
						href="/skills?search={encodeURIComponent(skill)}"
						class="font-mono text-[13px] text-fg-muted transition-[color] duration-150 hover:text-accent-primary hover:underline"
					>
						{skill}
					</a>
				{/each}
			</div>
		</ConfigSection>
	{/if}

	<!-- Sinks -->
	{#if detail.sinks.length > 0}
		<ConfigSection title="Sinks" count={detail.sinks.length}>
			<div class="space-y-1">
				{#each detail.sinks as sink}
					<div class="font-mono text-[13px]">
						<span class="text-accent-primary">{sink.type}</span>
						<span class="ml-1.5 text-fg-muted">{sink.summary}</span>
					</div>
				{/each}
			</div>
		</ConfigSection>
	{/if}

	<!-- Cognition -->
	{#if hasCognition}
		<ConfigSection title="Cognition">
			<div class="mb-2">
				<a
					href="https://www.initrunner.ai/docs/reasoning"
					target="_blank"
					rel="noopener"
					class="inline-flex items-center gap-1 font-mono text-[11px] text-accent-primary/60 transition-[color] duration-150 hover:text-accent-primary"
				>
					Docs <ExternalLink size={10} />
				</a>
			</div>
			<div class="space-y-3 font-mono text-[13px]" style="font-variant-numeric: tabular-nums">
				{#if reasoning}
					<div class="space-y-1">
						<div>
							<span class="text-fg-faint">pattern</span>
							<span class="ml-1 text-fg-muted">{reasoning.pattern ?? 'react'}</span>
						</div>
						{#if reasoning.auto_plan}
							<div>
								<span class="text-fg-faint">auto_plan</span>
								<span class="ml-1 text-fg-muted">true</span>
							</div>
						{/if}
						{#if reasoning.pattern === 'reflexion'}
							{#if reasoning.reflection_dimensions?.length}
								<div>
									<span class="text-fg-faint">dimensions</span>
									<span class="ml-1 text-fg-muted">{reasoning.reflection_dimensions.map(d => d.name).join(', ')}</span>
								</div>
							{:else if (reasoning.reflection_rounds ?? 0) > 0}
								<div>
									<span class="text-fg-faint">reflection_rounds</span>
									<span class="ml-1 text-fg-muted">{reasoning.reflection_rounds}</span>
								</div>
							{/if}
						{/if}
						{#if reasoning.auto_detect === false}
							<div>
								<span class="text-fg-faint">auto_detect</span>
								<span class="ml-1 text-fg-muted">false</span>
							</div>
						{/if}
					</div>
				{/if}

				{#if autonomy}
					<div class="space-y-1">
						<div class="text-fg-faint">autonomy</div>
						<div class="pl-2 space-y-1">
							<div>
								<span class="text-fg-faint">max plan steps</span>
								<span class="ml-1 text-fg-muted">{autonomy.max_plan_steps ?? 20}</span>
							</div>
							<div>
								<span class="text-fg-faint">max history</span>
								<span class="ml-1 text-fg-muted">{autonomy.max_history_messages ?? 40}</span>
							</div>
							{#if (autonomy.iteration_delay_seconds ?? 0) > 0}
								<div>
									<span class="text-fg-faint">delay</span>
									<span class="ml-1 text-fg-muted">{autonomy.iteration_delay_seconds}s</span>
								</div>
							{/if}
							{#if autonomy.compaction?.enabled}
								<div>
									<span class="text-fg-faint">compaction</span>
									<span class="ml-1 text-fg-muted">on (threshold: {autonomy.compaction.threshold ?? 30}, tail: {autonomy.compaction.tail_messages ?? 6})</span>
								</div>
							{/if}
						</div>
					</div>
				{/if}

				{#if thinkTool}
					<div>
						<span class="text-fg-faint">think</span>
						<span class="ml-1 text-fg-muted">
							{thinkTool.config.critique ? 'critique' : 'standard'}{thinkTool.config.max_thoughts ? `, ${thinkTool.config.max_thoughts} max` : ''}
						</span>
					</div>
				{/if}

				{#if todoTool}
					<div>
						<span class="text-fg-faint">todo</span>
						<span class="ml-1 text-fg-muted">
							{todoTool.config.max_items ?? 30} items{todoTool.config.shared ? ', shared' : ''}
						</span>
					</div>
				{/if}
			</div>
		</ConfigSection>
	{/if}

	<!-- Metadata (if any) -->
	{#if detail.author || detail.team || detail.version || detail.tags.length > 0}
		<ConfigSection title="Metadata" defaultOpen={false}>
			<div class="space-y-1 font-mono text-[13px]">
				{#if detail.author}
					<div>
						<span class="text-fg-faint">author</span>
						<span class="ml-1 text-fg-muted">{detail.author}</span>
					</div>
				{/if}
				{#if detail.team}
					<div>
						<span class="text-fg-faint">team</span>
						<span class="ml-1 text-fg-muted">{detail.team}</span>
					</div>
				{/if}
				{#if detail.version}
					<div>
						<span class="text-fg-faint">version</span>
						<span class="ml-1 text-fg-muted">{detail.version}</span>
					</div>
				{/if}
				{#if detail.tags.length > 0}
					<div>
						<span class="text-fg-faint">tags</span>
						<span class="ml-1 text-fg-muted">{detail.tags.join(', ')}</span>
					</div>
				{/if}
				<div>
					<span class="text-fg-faint">path</span>
					<span class="ml-1 text-fg-muted">{detail.path}</span>
				</div>
			</div>
		</ConfigSection>
	{/if}

	<!-- YAML (collapsed by default) -->
	{#if yaml}
		<ConfigSection title="YAML" defaultOpen={false}>
			<div class="overflow-hidden border border-edge">
				<div class="flex items-center justify-between border-b border-edge bg-surface-0 px-3 py-1.5">
					<span class="font-mono text-[13px] text-fg-faint">{detail.path.split('/').pop()}</span>
					<button
						class="flex items-center gap-1.5 text-[13px] text-fg-faint transition-[color] duration-150 hover:text-fg-muted"
						onclick={copyYaml}
						aria-label="Copy YAML"
					>
						{#if copied}
							<Check size={14} class="text-ok" />
							<span class="text-ok">Copied</span>
						{:else}
							<Copy size={14} />
							<span>Copy</span>
						{/if}
					</button>
				</div>
				<pre class="max-h-[400px] overflow-auto bg-surface-0 p-4 font-mono text-[13px] leading-relaxed text-fg-muted">{yaml}</pre>
			</div>
		</ConfigSection>
	{/if}
</div>
