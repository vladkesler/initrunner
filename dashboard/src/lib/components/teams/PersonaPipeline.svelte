<script lang="ts">
	import {
		SvelteFlow,
		Background,
		Controls,
		type Node,
		type Edge
	} from '@xyflow/svelte';
	import '@xyflow/svelte/dist/style.css';
	import type { TeamDetail, PersonaDetail, PersonaStepResponse } from '$lib/api/types';
	import PersonaNode from './PersonaNode.svelte';
	import AnchorNode from './AnchorNode.svelte';

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

	function personaState(name: string): 'active' | 'complete' | 'error' | 'pending' | 'idle' {
		if (!steps) return 'idle';
		if (activePersona === name) return 'active';
		const step = steps.find((s) => s.persona_name === name);
		if (!step) return 'pending';
		return step.success ? 'complete' : 'error';
	}

	function stepFor(name: string): PersonaStepResponse | null {
		return steps?.find((s) => s.persona_name === name) ?? null;
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
					style: 'stroke: oklch(0.91 0.20 128 / 0.6); stroke-width: 1.5px;'
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
					style: 'stroke: oklch(0.91 0.20 128 / 0.6); stroke-width: 1.5px;'
				});
			}
		}

		return { nodes, edges };
	}

	// ── Reactive state ────────────────────────────────────────────────

	const nodeTypes = { persona: PersonaNode, anchor: AnchorNode };

	const graph = $derived(buildGraph(detail.personas, detail.strategy, detail.handoff_max_chars));
	let nodes = $state.raw<Node[]>([]);
	let edges = $state.raw<Edge[]>([]);

	$effect(() => {
		nodes = graph.nodes;
		edges = graph.edges;
	});
</script>

<div style:width="100%" style:height="100%">
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
	</SvelteFlow>
</div>
