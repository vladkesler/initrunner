<script lang="ts">
	import {
		SvelteFlow,
		Background,
		Controls,
		MiniMap,
		Panel,
		type Node,
		type Edge
	} from '@xyflow/svelte';
	import '@xyflow/svelte/dist/style.css';
	import type { TeamDetail, PersonaDetail, PersonaStepResponse } from '$lib/api/types';
	import PersonaNode from './PersonaNode.svelte';
	import AnchorNode from './AnchorNode.svelte';
	import { RotateCcw } from 'lucide-svelte';

	let {
		detail,
		steps,
		activePersona
	}: {
		detail: TeamDetail;
		steps?: PersonaStepResponse[];
		activePersona?: string | null;
	} = $props();

	// ── Layout constants ──────────────────────────────────────────────
	const NODE_WIDTH = 240;
	const NODE_HEIGHT = 100;
	const ANCHOR_WIDTH = 200;
	const V_GAP = 80;
	const H_GAP = 40;
	const OFFSET_X = 60;
	const OFFSET_Y = 60;

	// ── State helpers ─────────────────────────────────────────────────

	function personaState(name: string, roundNum?: number): 'active' | 'complete' | 'error' | 'pending' | 'idle' {
		if (!steps) return 'idle';
		// For debate: match on display name pattern "name (round N)"
		const displayName = roundNum != null ? `${name} (round ${roundNum})` : name;
		if (activePersona === displayName) return 'active';
		const step = steps.find((s) =>
			roundNum != null
				? s.round_num === roundNum && s.persona_name === displayName
				: s.persona_name === name
		);
		if (!step) {
			// Check if active persona is in a later round (this round is done)
			if (roundNum != null && steps.some((s) => s.round_num === roundNum)) return 'idle';
			return 'pending';
		}
		return step.success ? 'complete' : 'error';
	}

	function stepFor(name: string, roundNum?: number): PersonaStepResponse | null {
		if (!steps) return null;
		if (roundNum != null) {
			const displayName = `${name} (round ${roundNum})`;
			return steps.find((s) => s.persona_name === displayName) ?? null;
		}
		return steps.find((s) => s.persona_name === name) ?? null;
	}

	// ── Graph builder ─────────────────────────────────────────────────

	function buildGraph(
		personas: PersonaDetail[],
		strategy: string,
		handoffMaxChars: number
	): { nodes: Node[]; edges: Edge[] } {
		const nodes: Node[] = [];
		const edges: Edge[] = [];

		if (strategy === 'sequential') {
			// Vertical chain
			for (let i = 0; i < personas.length; i++) {
				const p = personas[i];
				nodes.push({
					id: p.name,
					type: 'persona',
					position: { x: OFFSET_X, y: OFFSET_Y + i * (NODE_HEIGHT + V_GAP) },
					data: { persona: p, state: personaState(p.name), step: stepFor(p.name) },
					connectable: false,
					draggable: false
				});

				if (i < personas.length - 1) {
					edges.push({
						id: `e-${p.name}-${personas[i + 1].name}`,
						source: p.name,
						target: personas[i + 1].name,
						type: 'smoothstep',
						animated: true,
						label: `handoff ${handoffMaxChars.toLocaleString()}`,
						style: 'stroke: oklch(0.91 0.20 128); stroke-width: 2px;',
						labelStyle: 'fill: oklch(0.91 0.20 128 / 0.6); font-size: 10px; font-family: var(--font-mono);'
					});
				}
			}
		} else if (strategy === 'debate') {
			// Debate: rows of personas per round, connected vertically
			const maxRounds = detail.debate?.max_rounds ?? 3;
			const synthesize = detail.debate?.synthesize ?? true;
			const totalWidth = personas.length * NODE_WIDTH + (personas.length - 1) * H_GAP;
			const ROUND_GAP = 60; // gap between round label and persona row

			for (let r = 1; r <= maxRounds; r++) {
				const roundY = OFFSET_Y + (r - 1) * (NODE_HEIGHT + V_GAP + ROUND_GAP + 40);

				// Round label anchor
				const anchorX = OFFSET_X + (totalWidth - ANCHOR_WIDTH) / 2;
				nodes.push({
					id: `__round_${r}`,
					type: 'anchor',
					position: { x: anchorX, y: roundY },
					data: { label: `Round ${r}`, hasTarget: r > 1, hasSource: true },
					connectable: false,
					draggable: false
				});

				// Persona nodes in a row
				const personaY = roundY + 60 + ROUND_GAP;
				for (let i = 0; i < personas.length; i++) {
					const p = personas[i];
					const nodeId = `${p.name}_r${r}`;
					nodes.push({
						id: nodeId,
						type: 'persona',
						position: { x: OFFSET_X + i * (NODE_WIDTH + H_GAP), y: personaY },
						data: {
							persona: p,
							state: personaState(p.name, r),
							step: stepFor(p.name, r),
							isDebate: true
						},
						connectable: false,
						draggable: false
					});

					// Round anchor -> persona
					edges.push({
						id: `e-round${r}-${nodeId}`,
						source: `__round_${r}`,
						target: nodeId,
						type: 'smoothstep',
						animated: true,
						style: 'stroke: oklch(0.91 0.20 128); stroke-width: 2px;'
					});
				}

				// Personas -> next round anchor (except last round)
				if (r < maxRounds) {
					for (const p of personas) {
						edges.push({
							id: `e-${p.name}_r${r}-round${r + 1}`,
							source: `${p.name}_r${r}`,
							target: `__round_${r + 1}`,
							type: 'smoothstep',
							animated: true,
							style: 'stroke: oklch(0.91 0.20 128 / 0.4); stroke-width: 1px;'
						});
					}
				}
			}

			// Synthesis node (or output anchor)
			const lastRoundY = OFFSET_Y + (maxRounds - 1) * (NODE_HEIGHT + V_GAP + ROUND_GAP + 40);
			const synthY = lastRoundY + 60 + ROUND_GAP + NODE_HEIGHT + V_GAP;
			const anchorX = OFFSET_X + (totalWidth - ANCHOR_WIDTH) / 2;

			const synthLabel = synthesize ? 'Synthesis' : 'Final Output';
			nodes.push({
				id: '__synthesis',
				type: 'anchor',
				position: { x: anchorX, y: synthY },
				data: { label: synthLabel, hasTarget: true, hasSource: false },
				connectable: false,
				draggable: false
			});

			for (const p of personas) {
				edges.push({
					id: `e-${p.name}_r${maxRounds}-synth`,
					source: `${p.name}_r${maxRounds}`,
					target: '__synthesis',
					type: 'smoothstep',
					animated: true,
					style: 'stroke: oklch(0.91 0.20 128); stroke-width: 2px;'
				});
			}
		} else {
			// Parallel: input -> personas -> output
			const totalWidth = personas.length * NODE_WIDTH + (personas.length - 1) * H_GAP;
			const inputX = OFFSET_X + (totalWidth - ANCHOR_WIDTH) / 2;

			// Input anchor
			nodes.push({
				id: '__input',
				type: 'anchor',
				position: { x: inputX, y: OFFSET_Y },
				data: { label: 'Task Input', hasTarget: false, hasSource: true },
				connectable: false,
				draggable: false
			});

			// Persona nodes in a row
			const personaY = OFFSET_Y + 60 + V_GAP;
			for (let i = 0; i < personas.length; i++) {
				const p = personas[i];
				const x = OFFSET_X + i * (NODE_WIDTH + H_GAP);
				nodes.push({
					id: p.name,
					type: 'persona',
					position: { x, y: personaY },
					data: { persona: p, state: personaState(p.name), step: stepFor(p.name) },
					connectable: false,
					draggable: false
				});

				edges.push({
					id: `e-input-${p.name}`,
					source: '__input',
					target: p.name,
					type: 'smoothstep',
					animated: true,
					style: 'stroke: oklch(0.91 0.20 128); stroke-width: 2px;'
				});
			}

			// Output anchor
			const outputY = personaY + NODE_HEIGHT + V_GAP;
			nodes.push({
				id: '__output',
				type: 'anchor',
				position: { x: inputX, y: outputY },
				data: { label: 'Combined Output', hasTarget: true, hasSource: false },
				connectable: false,
				draggable: false
			});

			for (const p of personas) {
				edges.push({
					id: `e-${p.name}-output`,
					source: p.name,
					target: '__output',
					type: 'smoothstep',
					animated: true,
					style: 'stroke: oklch(0.91 0.20 128); stroke-width: 2px;'
				});
			}
		}

		return { nodes, edges };
	}

	// ── MiniMap colors ────────────────────────────────────────────────

	function minimapNodeColor(node: Node): string {
		if (node.type === 'anchor') return '#00e5ff';
		const st = node.data?.state as string | undefined;
		if (st === 'active') return '#c8ff00';
		if (st === 'error') return '#ff4d6a';
		if (st === 'complete') return '#34d399';
		return '#2a2a30';
	}

	// ── Reactive state ────────────────────────────────────────────────

	const nodeTypes = { persona: PersonaNode, anchor: AnchorNode };

	const graph = $derived(buildGraph(detail.personas, detail.strategy, detail.handoff_max_chars));
	let nodes = $state.raw<Node[]>([]);
	let edges = $state.raw<Edge[]>([]);
	let viewKey = $state(0);

	$effect(() => {
		nodes = graph.nodes;
		edges = graph.edges;
	});
</script>

<div style:width="100%" style:height="100%">
	{#key viewKey}
	<SvelteFlow
		bind:nodes
		bind:edges
		{nodeTypes}
		fitView
		fitViewOptions={{ padding: 0.3 }}
		colorMode="dark"
		nodesConnectable={false}
		nodesDraggable={false}
		deleteKey=""
		proOptions={{ hideAttribution: true }}
		minZoom={0.3}
		maxZoom={2}
	>
		<Background gap={24} size={1} />
		<Controls showInteractive={false} />
		<MiniMap nodeColor={minimapNodeColor} pannable zoomable />

		<Panel position="bottom-left">
			<button
				class="flex items-center gap-1.5 border border-edge bg-surface-0/90 px-3 py-1.5 font-mono text-[11px] text-fg-faint backdrop-blur-sm transition-[color,background-color] duration-150 hover:bg-surface-2 hover:text-fg-muted"
				onclick={() => viewKey++}
			>
				<RotateCcw size={12} strokeWidth={1.5} />
				Reset view
			</button>
		</Panel>
	</SvelteFlow>
	{/key}
</div>
