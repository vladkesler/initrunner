<script lang="ts">
	import yaml from 'js-yaml';
	import { Brain, ChevronRight, ExternalLink, Info } from 'lucide-svelte';

	let {
		yamlText,
		onUpdate,
		toolFuncMap = {}
	}: {
		yamlText: string;
		onUpdate: (newYaml: string) => void;
		toolFuncMap?: Record<string, string[]>;
	} = $props();

	// ── Parse YAML to derive cognition state ─────────────────────────

	interface CognitionState {
		reasoning: {
			pattern: string;
			auto_plan: boolean;
			reflection_rounds: number;
			reflection_dimensions: Array<{ name: string; prompt: string }> | null;
			auto_detect: boolean;
		};
		autonomy: {
			enabled: boolean;
			max_plan_steps: number;
			max_history_messages: number;
			iteration_delay_seconds: number;
			compaction: {
				enabled: boolean;
				threshold: number;
				tail_messages: number;
			};
		};
		think: {
			enabled: boolean;
			critique: boolean;
			max_thoughts: number;
		};
		todo: {
			enabled: boolean;
			max_items: number;
			shared: boolean;
			shared_path: string;
		};
		guardrails: {
			max_iterations: number;
			timeout_seconds: number;
		};
		toolSearch: {
			enabled: boolean;
			always_available: string[];
			max_results: number;
		};
	}

	const PATTERNS = ['react', 'todo_driven', 'plan_execute', 'reflexion'] as const;
	const REQUIRES_TODO = new Set(['todo_driven', 'plan_execute']);
	const PATTERN_TIPS: Record<string, string> = {
		react: 'Simple tool loop. Agent reasons, picks a tool, observes, repeats.',
		todo_driven: 'Agent maintains a todo list and works through items one by one.',
		plan_execute: 'Agent creates a plan upfront, then executes each step.',
		reflexion: 'Agent critiques its own output and retries to improve quality.',
	};

	function parseState(text: string): CognitionState {
		try {
			const doc = yaml.load(text) as Record<string, any> | null;
			const spec = doc?.spec ?? {};
			const tools: any[] = spec.tools ?? [];
			const thinkTool = tools.find((t: any) => t?.type === 'think');
			const todoTool = tools.find((t: any) => t?.type === 'todo');
			const r = spec.reasoning ?? {};
			const a = spec.autonomy;
			const g = spec.guardrails ?? {};
			const ts = spec.tool_search ?? {};

			return {
				reasoning: {
					pattern: r.pattern ?? 'react',
					auto_plan: r.auto_plan ?? false,
					reflection_rounds: r.reflection_rounds ?? 0,
					reflection_dimensions: r.reflection_dimensions ?? null,
					auto_detect: r.auto_detect ?? true,
				},
				autonomy: {
					enabled: !!a,
					max_plan_steps: a?.max_plan_steps ?? 20,
					max_history_messages: a?.max_history_messages ?? 40,
					iteration_delay_seconds: a?.iteration_delay_seconds ?? 0,
					compaction: {
						enabled: a?.compaction?.enabled ?? false,
						threshold: a?.compaction?.threshold ?? 30,
						tail_messages: a?.compaction?.tail_messages ?? 6,
					},
				},
				think: {
					enabled: !!thinkTool,
					critique: thinkTool?.critique ?? false,
					max_thoughts: thinkTool?.max_thoughts ?? 50,
				},
				todo: {
					enabled: !!todoTool,
					max_items: todoTool?.max_items ?? 30,
					shared: todoTool?.shared ?? false,
					shared_path: todoTool?.shared_path ?? '',
				},
				guardrails: {
					max_iterations: g.max_iterations ?? 10,
					timeout_seconds: g.timeout_seconds ?? 300,
				},
				toolSearch: {
					enabled: ts.enabled ?? false,
					always_available: ts.always_available ?? [],
					max_results: ts.max_results ?? 5,
				},
			};
		} catch {
			return defaultState();
		}
	}

	function defaultState(): CognitionState {
		return {
			reasoning: { pattern: 'react', auto_plan: false, reflection_rounds: 0, auto_detect: true },
			autonomy: { enabled: false, max_plan_steps: 20, max_history_messages: 40, iteration_delay_seconds: 0, compaction: { enabled: false, threshold: 30, tail_messages: 6 } },
			think: { enabled: false, critique: false, max_thoughts: 50 },
			todo: { enabled: false, max_items: 30, shared: false, shared_path: '' },
			guardrails: { max_iterations: 10, timeout_seconds: 300 },
			toolSearch: { enabled: false, always_available: [], max_results: 5 },
		};
	}

	let cog = $derived(parseState(yamlText));

	// ── Write state back to YAML ─────────────────────────────────────

	function applyChange(mutate: (doc: Record<string, any>) => void) {
		try {
			const doc = (yaml.load(yamlText) as Record<string, any>) ?? {};
			if (!doc.spec) doc.spec = {};
			mutate(doc);
			const dumped = yaml.dump(doc, { lineWidth: -1, noRefs: true, sortKeys: false, quotingType: '"' });
			onUpdate(dumped);
		} catch {
			// If YAML is malformed, don't apply
		}
	}

	function findToolIndex(tools: any[], type: string): number {
		return tools.findIndex((t: any) => t?.type === type);
	}

	function setPattern(pattern: string) {
		applyChange((doc) => {
			if (!doc.spec.reasoning) doc.spec.reasoning = {};
			doc.spec.reasoning.pattern = pattern;
			if (pattern === 'reflexion' && !doc.spec.reasoning.reflection_rounds && !doc.spec.reasoning.reflection_dimensions) {
				doc.spec.reasoning.reflection_rounds = 2;
			}
		});
	}

	function setReasoningField(field: string, value: any) {
		applyChange((doc) => {
			if (!doc.spec.reasoning) doc.spec.reasoning = {};
			doc.spec.reasoning[field] = value;
		});
	}

	function toggleAutonomy(enabled: boolean) {
		applyChange((doc) => {
			if (enabled) {
				doc.spec.autonomy = { max_plan_steps: 20, max_history_messages: 40, iteration_delay_seconds: 0 };
			} else {
				delete doc.spec.autonomy;
			}
		});
	}

	function setAutonomyField(field: string, value: any) {
		applyChange((doc) => {
			if (!doc.spec.autonomy) return;
			doc.spec.autonomy[field] = value;
		});
	}

	function toggleCompaction(enabled: boolean) {
		applyChange((doc) => {
			if (!doc.spec.autonomy) return;
			if (enabled) {
				doc.spec.autonomy.compaction = { enabled: true, threshold: 30, tail_messages: 6 };
			} else {
				delete doc.spec.autonomy.compaction;
			}
		});
	}

	function setCompactionField(field: string, value: any) {
		applyChange((doc) => {
			if (!doc.spec.autonomy?.compaction) return;
			doc.spec.autonomy.compaction[field] = value;
		});
	}

	function toggleTool(type: string, enabled: boolean, defaults: Record<string, any>) {
		applyChange((doc) => {
			if (!doc.spec.tools) doc.spec.tools = [];
			const idx = findToolIndex(doc.spec.tools, type);
			if (enabled && idx === -1) {
				doc.spec.tools.push({ type, ...defaults });
			} else if (!enabled && idx !== -1) {
				doc.spec.tools.splice(idx, 1);
			}
		});
	}

	function setToolField(type: string, field: string, value: any) {
		applyChange((doc) => {
			if (!doc.spec.tools) return;
			const idx = findToolIndex(doc.spec.tools, type);
			if (idx === -1) return;
			doc.spec.tools[idx][field] = value;
		});
	}

	function addTodoTool() {
		toggleTool('todo', true, { max_items: 30 });
	}

	// ── Tool search helpers ─────────────────────────────────────────

	const toolCount = $derived.by(() => {
		try {
			const doc = yaml.load(yamlText) as Record<string, any> | null;
			return (doc?.spec?.tools ?? []).length;
		} catch { return 0; }
	});

	const resolvedFuncs = $derived.by(() => {
		try {
			const doc = yaml.load(yamlText) as Record<string, any> | null;
			const tools: any[] = doc?.spec?.tools ?? [];
			const result: { func_name: string; tool_type: string }[] = [];
			for (const t of tools) {
				const type = t?.type;
				if (type && toolFuncMap[type]) {
					for (const fn of toolFuncMap[type]) {
						result.push({ func_name: fn, tool_type: type });
					}
				}
			}
			return result;
		} catch { return []; }
	});

	const showToolSearch = $derived(toolCount >= 10 || cog.toolSearch.enabled);

	const AUTO_PIN_FUNCS = ['current_time', 'parse_date', 'think', 'search_documents'];

	function toggleToolSearch(enabled: boolean) {
		applyChange((doc) => {
			if (enabled) {
				const autoPin = resolvedFuncs
					.filter((f) => AUTO_PIN_FUNCS.includes(f.func_name))
					.map((f) => f.func_name);
				doc.spec.tool_search = { enabled: true, always_available: autoPin, max_results: 5 };
			} else {
				delete doc.spec.tool_search;
			}
		});
	}

	function setToolSearchAlwaysAvailable(funcNames: string[]) {
		applyChange((doc) => {
			if (!doc.spec.tool_search) return;
			doc.spec.tool_search.always_available = funcNames;
		});
	}

	function setToolSearchMaxResults(value: number) {
		applyChange((doc) => {
			if (!doc.spec.tool_search) return;
			doc.spec.tool_search.max_results = value;
		});
	}

	// ── Sub-section expand state ─────────────────────────────────────

	let autonomyOpen = $state(true);
	let compactionOpen = $state(false);
	let toolSearchTuningOpen = $state(false);

	const needsTodo = $derived(REQUIRES_TODO.has(cog.reasoning.pattern) && !cog.todo.enabled);
	const todoForced = $derived(REQUIRES_TODO.has(cog.reasoning.pattern));
</script>

<div class="space-y-4">
	<!-- Header -->
	<div class="flex items-center gap-2">
		<Brain size={14} strokeWidth={1.5} class="text-fg-faint" />
		<span class="font-mono text-[12px] font-medium uppercase tracking-[0.1em] text-fg-faint">
			Cognition
		</span>
		<div class="flex-1"></div>
		<a
			href="https://www.initrunner.ai/docs/reasoning"
			target="_blank"
			rel="noopener"
			class="inline-flex items-center gap-1 font-mono text-[11px] text-accent-primary/60 transition-[color] duration-150 hover:text-accent-primary"
		>
			Docs <ExternalLink size={10} />
		</a>
	</div>

	<!-- Reasoning Pattern -->
	<div class="space-y-2">
		<div class="font-mono text-[11px] font-medium uppercase tracking-[0.08em] text-fg-faint" title="Reasoning strategy the agent uses to solve problems. react: tool loop, todo_driven: maintains a task list, plan_execute: plans then acts, reflexion: self-critiques and retries.">
			Pattern
		</div>
		<div class="grid grid-cols-2 gap-1">
			{#each PATTERNS as p}
				<button
					class="px-2 py-1.5 font-mono text-[12px] transition-[color,background-color,border-color] duration-150 border
						{cog.reasoning.pattern === p
							? 'border-accent-primary/30 bg-accent-primary/10 text-accent-primary'
							: 'border-edge bg-surface-1 text-fg-faint hover:text-fg-muted hover:bg-surface-2'}"
					onclick={() => setPattern(p)}
					title={PATTERN_TIPS[p]}
				>
					{p}
				</button>
			{/each}
		</div>

		{#if needsTodo}
			<div class="flex items-start gap-2 border-l-2 border-l-warn bg-warn/5 px-2.5 py-2">
				<Info size={12} class="mt-0.5 shrink-0 text-warn" />
				<div class="flex-1">
					<span class="font-mono text-[12px] text-warn">Requires a todo tool.</span>
					<button
						class="ml-2 font-mono text-[12px] text-accent-primary underline decoration-accent-primary/30 hover:decoration-accent-primary"
						onclick={addTodoTool}
					>
						Add todo tool
					</button>
				</div>
			</div>
		{/if}

		{#if cog.reasoning.pattern === 'reflexion'}
			{#if cog.reasoning.reflection_dimensions?.length}
				<div class="flex flex-col gap-1 pl-0.5">
					<span class="font-mono text-[12px] text-fg-faint">dimensions</span>
					{#each cog.reasoning.reflection_dimensions as dim}
						<span class="font-mono text-[12px] text-fg-muted">{dim.name}</span>
					{/each}
				</div>
			{:else}
				<label class="flex items-center gap-3 pl-0.5">
					<span class="font-mono text-[12px] text-fg-faint">reflection_rounds</span>
					<input
						type="number"
						min="1"
						max="3"
						value={cog.reasoning.reflection_rounds || 2}
						onchange={(e) => setReasoningField('reflection_rounds', parseInt(e.currentTarget.value) || 2)}
						class="w-14 border border-edge bg-surface-1 px-2 py-1 font-mono text-[12px] text-fg-muted outline-none focus:border-accent-primary/40"
						style="font-variant-numeric: tabular-nums"
					/>
				</label>
			{/if}
		{/if}

		{#if cog.reasoning.pattern === 'todo_driven' || cog.reasoning.pattern === 'plan_execute'}
			<label class="flex items-center gap-2 pl-0.5 font-mono text-[12px] text-fg-faint" title="Automatically generate an initial plan before the first tool call.">
				<input
					type="checkbox"
					checked={cog.reasoning.auto_plan}
					onchange={(e) => setReasoningField('auto_plan', e.currentTarget.checked)}
					class="accent-accent-primary"
				/>
				auto_plan
			</label>
		{/if}

		<label class="flex items-center gap-2 pl-0.5 font-mono text-[12px] text-fg-faint" title="Automatically detect which reasoning pattern to use based on the prompt.">
			<input
				type="checkbox"
				checked={cog.reasoning.auto_detect}
				onchange={(e) => setReasoningField('auto_detect', e.currentTarget.checked)}
				class="accent-accent-primary"
			/>
			auto_detect
		</label>
	</div>

	<!-- Autonomy -->
	<div class="space-y-2">
		{#if cog.autonomy.enabled}
			<button
				class="flex w-full items-center gap-1.5"
				onclick={() => (autonomyOpen = !autonomyOpen)}
				title="Agent runs multiple iterations independently without waiting for user input."
			>
				<ChevronRight
					size={11}
					class="shrink-0 text-fg-faint transition-transform duration-150 {autonomyOpen ? 'rotate-90' : ''}"
				/>
				<span class="font-mono text-[11px] font-medium uppercase tracking-[0.08em] text-fg-faint">
					Autonomy
				</span>
				<div class="flex-1"></div>
				<!-- svelte-ignore a11y_no_static_element_interactions, a11y_click_events_have_key_events -->
				<span class="flex items-center" role="presentation" onclick={(e) => e.stopPropagation()}>
					<input
						type="checkbox"
						checked={cog.autonomy.enabled}
						onchange={(e) => toggleAutonomy(e.currentTarget.checked)}
						class="accent-accent-primary"
						aria-label="Enable autonomy"
					/>
				</span>
			</button>
		{:else}
			<label class="flex items-center gap-1.5" title="Agent runs multiple iterations independently without waiting for user input.">
				<span class="font-mono text-[11px] font-medium uppercase tracking-[0.08em] text-fg-faint">
					Autonomy
				</span>
				<div class="flex-1"></div>
				<input
					type="checkbox"
					checked={false}
					onchange={(e) => toggleAutonomy(e.currentTarget.checked)}
					class="accent-accent-primary"
					aria-label="Enable autonomy"
				/>
			</label>
		{/if}

		{#if cog.autonomy.enabled && !REQUIRES_TODO.has(cog.reasoning.pattern) && cog.reasoning.pattern === 'react'}
			<div class="flex items-start gap-2 px-2.5 py-1.5">
				<Info size={12} class="mt-0.5 shrink-0 text-fg-faint" />
				<span class="font-mono text-[11px] text-fg-faint">Consider todo_driven or plan_execute for autonomous agents.</span>
			</div>
		{/if}

		{#if autonomyOpen && cog.autonomy.enabled}
			<div class="space-y-2 pl-4">
				<label class="flex items-center gap-3">
					<span class="w-28 font-mono text-[12px] text-fg-faint">plan steps</span>
					<input
						type="number"
						min="1"
						max="100"
						value={cog.autonomy.max_plan_steps}
						onchange={(e) => setAutonomyField('max_plan_steps', parseInt(e.currentTarget.value) || 20)}
						class="w-16 border border-edge bg-surface-1 px-2 py-1 font-mono text-[12px] text-fg-muted outline-none focus:border-accent-primary/40"
						style="font-variant-numeric: tabular-nums"
					/>
				</label>
				<label class="flex items-center gap-3">
					<span class="w-28 font-mono text-[12px] text-fg-faint">max history</span>
					<input
						type="number"
						min="1"
						max="200"
						value={cog.autonomy.max_history_messages}
						onchange={(e) => setAutonomyField('max_history_messages', parseInt(e.currentTarget.value) || 40)}
						class="w-16 border border-edge bg-surface-1 px-2 py-1 font-mono text-[12px] text-fg-muted outline-none focus:border-accent-primary/40"
						style="font-variant-numeric: tabular-nums"
					/>
				</label>
				<label class="flex items-center gap-3">
					<span class="w-28 font-mono text-[12px] text-fg-faint">delay</span>
					<input
						type="number"
						min="0"
						max="60"
						value={cog.autonomy.iteration_delay_seconds}
						onchange={(e) => setAutonomyField('iteration_delay_seconds', parseFloat(e.currentTarget.value) || 0)}
						class="w-16 border border-edge bg-surface-1 px-2 py-1 font-mono text-[12px] text-fg-muted outline-none focus:border-accent-primary/40"
						style="font-variant-numeric: tabular-nums"
					/>
					<span class="font-mono text-[11px] text-fg-faint">s</span>
				</label>

				<!-- Compaction -->
				<button
					class="flex w-full items-center gap-1.5 pt-1"
					onclick={() => (compactionOpen = !compactionOpen)}
				>
					<ChevronRight
						size={10}
						class="shrink-0 text-fg-faint transition-transform duration-150 {compactionOpen ? 'rotate-90' : ''}"
					/>
					<span class="font-mono text-[11px] text-fg-faint">compaction</span>
					<div class="flex-1"></div>
					<!-- svelte-ignore a11y_no_static_element_interactions, a11y_click_events_have_key_events -->
					<span class="flex items-center" role="presentation" onclick={(e) => e.stopPropagation()}>
						<input
							type="checkbox"
							checked={cog.autonomy.compaction.enabled}
							onchange={(e) => toggleCompaction(e.currentTarget.checked)}
							class="accent-accent-primary"
							aria-label="Enable compaction"
						/>
					</span>
				</button>

				{#if compactionOpen && cog.autonomy.compaction.enabled}
					<div class="space-y-2 pl-4">
						<label class="flex items-center gap-3">
							<span class="w-24 font-mono text-[12px] text-fg-faint">threshold</span>
							<input
								type="number"
								min="1"
								max="200"
								value={cog.autonomy.compaction.threshold}
								onchange={(e) => setCompactionField('threshold', parseInt(e.currentTarget.value) || 30)}
								class="w-16 border border-edge bg-surface-1 px-2 py-1 font-mono text-[12px] text-fg-muted outline-none focus:border-accent-primary/40"
								style="font-variant-numeric: tabular-nums"
							/>
						</label>
						<label class="flex items-center gap-3">
							<span class="w-24 font-mono text-[12px] text-fg-faint">tail</span>
							<input
								type="number"
								min="1"
								max="20"
								value={cog.autonomy.compaction.tail_messages}
								onchange={(e) => setCompactionField('tail_messages', parseInt(e.currentTarget.value) || 6)}
								class="w-16 border border-edge bg-surface-1 px-2 py-1 font-mono text-[12px] text-fg-muted outline-none focus:border-accent-primary/40"
								style="font-variant-numeric: tabular-nums"
							/>
						</label>
					</div>
				{/if}
			</div>
		{/if}
	</div>

	<!-- Think Tool -->
	<div class="space-y-2">
		<label class="flex items-center gap-1.5" title="Gives the agent a scratchpad for internal reasoning before acting. Critique mode adds self-evaluation.">
			<span class="font-mono text-[11px] font-medium uppercase tracking-[0.08em] text-fg-faint">
				Think
			</span>
			<div class="flex-1"></div>
			<input
				type="checkbox"
				checked={cog.think.enabled}
				onchange={(e) => toggleTool('think', e.currentTarget.checked, { critique: false, max_thoughts: 50 })}
				class="accent-accent-primary"
			/>
		</label>

		{#if cog.reasoning.pattern === 'reflexion' && !cog.think.enabled}
			<div class="flex items-start gap-2 px-2.5 py-1.5">
				<Info size={12} class="mt-0.5 shrink-0 text-fg-faint" />
				<span class="font-mono text-[11px] text-fg-faint">Think tool with critique recommended for reflexion.</span>
			</div>
		{/if}

		{#if cog.think.enabled}
			<div class="flex items-center gap-4 pl-4">
				<label class="flex items-center gap-2 font-mono text-[12px] text-fg-faint">
					<input
						type="checkbox"
						checked={cog.think.critique}
						onchange={(e) => setToolField('think', 'critique', e.currentTarget.checked)}
						class="accent-accent-primary"
					/>
					critique
				</label>
				<label class="flex items-center gap-2">
					<span class="font-mono text-[12px] text-fg-faint">max</span>
					<input
						type="number"
						min="1"
						max="200"
						value={cog.think.max_thoughts}
						onchange={(e) => setToolField('think', 'max_thoughts', parseInt(e.currentTarget.value) || 50)}
						class="w-14 border border-edge bg-surface-1 px-2 py-1 font-mono text-[12px] text-fg-muted outline-none focus:border-accent-primary/40"
						style="font-variant-numeric: tabular-nums"
					/>
				</label>
			</div>
		{/if}
	</div>

	<!-- Todo Tool -->
	<div class="space-y-2">
		<label class="flex items-center gap-1.5" title="Agent tracks tasks in a structured list. Required for todo_driven and plan_execute patterns.">
			<span class="font-mono text-[11px] font-medium uppercase tracking-[0.08em] text-fg-faint">
				Todo
			</span>
			<div class="flex-1"></div>
			<input
				type="checkbox"
				checked={cog.todo.enabled}
				disabled={todoForced}
				onchange={(e) => toggleTool('todo', e.currentTarget.checked, { max_items: 30 })}
				class="accent-accent-primary disabled:opacity-50"
			/>
		</label>

		{#if cog.todo.enabled}
			<div class="space-y-2 pl-4">
				<label class="flex items-center gap-3">
					<span class="w-20 font-mono text-[12px] text-fg-faint">max items</span>
					<input
						type="number"
						min="1"
						max="100"
						value={cog.todo.max_items}
						onchange={(e) => setToolField('todo', 'max_items', parseInt(e.currentTarget.value) || 30)}
						class="w-14 border border-edge bg-surface-1 px-2 py-1 font-mono text-[12px] text-fg-muted outline-none focus:border-accent-primary/40"
						style="font-variant-numeric: tabular-nums"
					/>
				</label>
				<label class="flex items-center gap-2 font-mono text-[12px] text-fg-faint">
					<input
						type="checkbox"
						checked={cog.todo.shared}
						onchange={(e) => {
							const checked = e.currentTarget.checked;
							applyChange((doc) => {
								if (!doc.spec.tools) return;
								const idx = findToolIndex(doc.spec.tools, 'todo');
								if (idx === -1) return;
								doc.spec.tools[idx].shared = checked;
								if (checked && !doc.spec.tools[idx].shared_path) {
									doc.spec.tools[idx].shared_path = '.todo.json';
								}
								if (!checked) {
									delete doc.spec.tools[idx].shared_path;
								}
							});
						}}
						class="accent-accent-primary"
					/>
					persist across runs
				</label>
				{#if !cog.todo.shared}
					<div class="font-mono text-[11px] text-fg-faint/60">Saves todo list to a file so it survives across runs.</div>
				{/if}
				{#if cog.todo.shared}
					<label class="flex items-center gap-3">
						<span class="w-20 font-mono text-[12px] text-fg-faint">path</span>
						<input
							type="text"
							value={cog.todo.shared_path}
							onchange={(e) => setToolField('todo', 'shared_path', e.currentTarget.value)}
							class="min-w-0 flex-1 border border-edge bg-surface-1 px-2 py-1 font-mono text-[12px] text-fg-muted outline-none focus:border-accent-primary/40"
							placeholder="/tmp/todo.json"
						/>
					</label>
				{/if}
			</div>
		{/if}
	</div>

	<!-- Tool Search -->
	<div class="space-y-2 border-t border-edge pt-3">
			<label class="flex items-center gap-1.5" title="Hides tools behind on-demand keyword discovery. The agent calls search_tools() to find what it needs. Reduces context and improves accuracy for agents with many tools.">
				<span class="font-mono text-[11px] font-medium uppercase tracking-[0.08em] text-fg-faint">
					Tool Search
				</span>
				<div class="flex-1"></div>
				<input
					type="checkbox"
					checked={cog.toolSearch.enabled}
					onchange={(e) => toggleToolSearch(e.currentTarget.checked)}
					class="accent-accent-primary"
				/>
			</label>

			{#if !cog.toolSearch.enabled && toolCount >= 10}
				<div class="flex items-start gap-2 border-l-2 border-l-info bg-info/5 px-2.5 py-2">
					<Info size={12} class="mt-0.5 shrink-0 text-info" />
					<div class="flex-1">
						<span class="font-mono text-[12px] text-fg-faint">
							This agent has {toolCount} tools. Tool search hides tools behind on-demand discovery. Typically saves 60-80% context and improves accuracy.
						</span>
						<button
							class="ml-2 font-mono text-[12px] text-accent-primary underline decoration-accent-primary/30 hover:decoration-accent-primary"
							onclick={() => toggleToolSearch(true)}
						>
							Enable
						</button>
					</div>
				</div>
			{/if}

			{#if cog.toolSearch.enabled}
				<div class="space-y-2 pl-0.5">
					<div class="flex items-center justify-between">
						<span class="font-mono text-[10px] font-medium uppercase tracking-[0.08em] text-fg-faint/60">Always visible</span>
						<span class="font-mono text-[10px] text-fg-faint/60">{cog.toolSearch.always_available.length} / {resolvedFuncs.length}</span>
					</div>
					<div class="max-h-40 space-y-0.5 overflow-y-auto">
						{#each resolvedFuncs as func}
							{@const checked = cog.toolSearch.always_available.includes(func.func_name)}
							<label class="flex items-center gap-2 py-0.5">
								<input
									type="checkbox"
									{checked}
									onchange={() => {
										const current = [...cog.toolSearch.always_available];
										if (checked) {
											setToolSearchAlwaysAvailable(current.filter((n) => n !== func.func_name));
										} else {
											setToolSearchAlwaysAvailable([...current, func.func_name]);
										}
									}}
									class="accent-accent-primary"
								/>
								<span class="font-mono text-[12px] text-fg-muted">{func.func_name}</span>
								<span class="font-mono text-[10px] text-fg-faint/40">({func.tool_type})</span>
							</label>
						{/each}
					</div>
					<div class="font-mono text-[11px] text-fg-faint/60">
						Unchecked tools are discoverable via search_tools at runtime.
					</div>

					<!-- Tuning -->
					<button
						class="flex items-center gap-1 pt-1"
						onclick={() => (toolSearchTuningOpen = !toolSearchTuningOpen)}
					>
						<ChevronRight
							size={10}
							class="shrink-0 text-fg-faint transition-transform duration-150 {toolSearchTuningOpen ? 'rotate-90' : ''}"
						/>
						<span class="font-mono text-[10px] font-medium uppercase tracking-[0.08em] text-fg-faint/60">Tuning</span>
					</button>

					{#if toolSearchTuningOpen}
						<div class="pl-4">
							<label class="flex items-center gap-3">
								<span class="w-24 font-mono text-[12px] text-fg-faint">max results</span>
								<input
									type="number"
									min="1"
									max="20"
									value={cog.toolSearch.max_results}
									onchange={(e) => setToolSearchMaxResults(parseInt(e.currentTarget.value) || 5)}
									class="w-14 border border-edge bg-surface-1 px-2 py-1 font-mono text-[12px] text-fg-muted outline-none focus:border-accent-primary/40"
									style="font-variant-numeric: tabular-nums"
								/>
							</label>
						</div>
					{/if}
				</div>
			{/if}
		</div>

	<!-- Guardrails readout -->
	<div class="border-t border-edge pt-3">
		<div class="font-mono text-[11px] font-medium uppercase tracking-[0.08em] text-fg-faint" title="Safety limits. Max iterations caps tool call loops. Timeout kills runs that exceed the time limit.">
			Guardrails
		</div>
		<div class="mt-1.5 flex gap-4 font-mono text-[12px]" style="font-variant-numeric: tabular-nums">
			<span>
				<span class="text-fg-faint">iterations</span>
				<span class="ml-1 text-fg-muted">{cog.guardrails.max_iterations}</span>
			</span>
			<span>
				<span class="text-fg-faint">timeout</span>
				<span class="ml-1 text-fg-muted">{cog.guardrails.timeout_seconds}s</span>
			</span>
		</div>
	</div>
</div>
