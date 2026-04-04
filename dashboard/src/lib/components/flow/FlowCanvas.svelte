<script lang="ts">
	import { untrack } from 'svelte';
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
	import { goto } from '$app/navigation';
	import type { FlowDetail, FlowAgentDetail } from '$lib/api/types';
	import AgentNode from './AgentNode.svelte';
	import { safeGet, safeSet } from '$lib/utils/storage';
	import { RotateCcw } from 'lucide-svelte';

	let {
		detail,
		onAgentClick
	}: {
		detail: FlowDetail;
		onAgentClick?: (name: string) => void;
	} = $props();

	// -- Layout constants -------------------------------------------------------
	const TIER_PITCH = 320;
	const NODE_PITCH = 140;
	const OFFSET_X = 60;
	const OFFSET_Y = 60;

	const storageKey = $derived(`flow-node-positions-${detail.id}`);

	function loadSavedPositions(): Record<string, { x: number; y: number }> {
		const raw = safeGet(storageKey);
		if (!raw) return {};
		try { return JSON.parse(raw); } catch { return {}; }
	}

	function savePosition(id: string, pos: { x: number; y: number }) {
		const saved = loadSavedPositions();
		saved[id] = { x: Math.round(pos.x), y: Math.round(pos.y) };
		safeSet(storageKey, JSON.stringify(saved));
	}

	function clearSavedPositions() {
		safeSet(storageKey, '');
	}

	// -- Topological tiering ----------------------------------------------------

	/** Kahn's algorithm: assign tier indices based on edges. */
	function computeTiers(
		agents: FlowAgentDetail[],
		edgeFn: (agt: FlowAgentDetail) => string[]
	): Map<string, number> {
		const names = new Set(agents.map((a) => a.name));
		const inDegree = new Map<string, number>();
		const adj = new Map<string, string[]>();
		for (const name of names) {
			inDegree.set(name, 0);
			adj.set(name, []);
		}

		for (const agt of agents) {
			// edgeFn returns what this agent depends on / receives from
			for (const dep of edgeFn(agt)) {
				if (names.has(dep)) {
					adj.get(dep)!.push(agt.name);
					inDegree.set(agt.name, (inDegree.get(agt.name) ?? 0) + 1);
				}
			}
		}

		const tiers = new Map<string, number>();
		const queue: string[] = [];
		for (const [name, deg] of inDegree) {
			if (deg === 0) queue.push(name);
		}

		let tier = 0;
		while (queue.length > 0) {
			const batch = [...queue];
			queue.length = 0;
			for (const name of batch) {
				tiers.set(name, tier);
				for (const next of adj.get(name) ?? []) {
					const newDeg = (inDegree.get(next) ?? 1) - 1;
					inDegree.set(next, newDeg);
					if (newDeg === 0) queue.push(next);
				}
			}
			tier++;
		}

		// Assign any remaining (cycle members) to last tier
		for (const name of names) {
			if (!tiers.has(name)) tiers.set(name, tier);
		}

		return tiers;
	}

	function buildLayout(agents: FlowAgentDetail[]): Map<string, number> {
		// Primary: tier by needs
		const depTiers = computeTiers(agents, (agt) => agt.needs);

		// If needs produces a single tier, fall back to sink.targets
		const maxTier = Math.max(...depTiers.values(), 0);
		if (maxTier === 0 && agents.length > 1) {
			// All in tier 0 -- try sink targets as reverse edges
			const sinkTiers = computeTiers(agents, (agt) =>
				// Sink targets mean "I send to these" -- so for tiering,
				// an agent that receives (is a target) depends on the sender.
				// We want senders in earlier tiers, so we invert: if X sends to Y,
				// Y's "dependency" is X. But our edgeFn returns what agt depends on.
				// So for each agent, find who sends TO it.
				agents
					.filter((a) => a.sink?.targets.includes(agt.name))
					.map((a) => a.name)
			);
			return sinkTiers;
		}

		return depTiers;
	}

	// -- Build nodes & edges ----------------------------------------------------

	function buildGraph(agts: FlowAgentDetail[]): { nodes: Node[]; edges: Edge[] } {
		const tiers = buildLayout(agts);
		const savedPositions = loadSavedPositions();

		// Group by tier for vertical stacking
		const tierGroups = new Map<number, FlowAgentDetail[]>();
		for (const agt of agts) {
			const t = tiers.get(agt.name) ?? 0;
			if (!tierGroups.has(t)) tierGroups.set(t, []);
			tierGroups.get(t)!.push(agt);
		}

		const nodes: Node[] = [];
		for (const [tier, group] of tierGroups) {
			for (let i = 0; i < group.length; i++) {
				const agt = group[i];
				const saved = savedPositions[agt.name];
				nodes.push({
					id: agt.name,
					type: 'flowAgent',
					position: saved ?? {
						x: OFFSET_X + tier * TIER_PITCH,
						y: OFFSET_Y + i * NODE_PITCH
					},
					data: { agent: agt },
					connectable: false
				});
			}
		}

		const edges: Edge[] = [];

		// Delegation edges (solid, lime)
		for (const agt of agts) {
			if (!agt.sink) continue;
			for (const target of agt.sink.targets) {
				const label = agt.sink.strategy !== 'all' ? agt.sink.strategy : undefined;
				edges.push({
					id: `delegate-${agt.name}-${target}`,
					source: agt.name,
					target,
					type: 'default',
					animated: true,
					label,
					style: 'stroke: oklch(0.91 0.20 128); stroke-width: 2px;',
					labelStyle: 'fill: oklch(0.91 0.20 128); font-size: 10px; font-family: var(--font-mono);'
				});
			}
		}

		// Dependency edges (dashed, muted): dep -> agent
		// Skip when a delegation edge already covers the same pair
		const delegateKeys = new Set(
			edges.filter((e) => e.id.startsWith('delegate-')).map((e) => `${e.source}->${e.target}`)
		);
		for (const agt of agts) {
			for (const dep of agt.needs) {
				if (delegateKeys.has(`${dep}->${agt.name}`)) continue;
				edges.push({
					id: `dep-${dep}-${agt.name}`,
					source: dep,
					target: agt.name,
					type: 'smoothstep',
					animated: false,
					style: 'stroke: oklch(0.50 0.02 260); stroke-width: 1px; stroke-dasharray: 5 3;'
				});
			}
		}

		return { nodes, edges };
	}

	// -- State ------------------------------------------------------------------

	const nodeTypes = { flowAgent: AgentNode };
	// svelte-ignore state_referenced_locally
	const initial = buildGraph(detail.agents);
	let nodes = $state.raw<Node[]>(initial.nodes);
	let edges = $state.raw<Edge[]>(initial.edges);

	// -- Events -----------------------------------------------------------------

	let lastClickTime = $state(0);

	function onnodeclick(_event: MouseEvent, node: Node) {
		const now = Date.now();
		const agt = node.data?.agent as FlowAgentDetail | undefined;
		if (!agt) return;

		if (now - lastClickTime < 400 && agt.agent_id) {
			// Double click -> navigate to agent
			goto(`/agents/${agt.agent_id}`);
		} else {
			onAgentClick?.(agt.name);
		}
		lastClickTime = now;
	}

	function onnodedragstop(_event: MouseEvent, node: Node) {
		savePosition(node.id, node.position);
	}

	function minimapNodeColor(node: Node): string {
		const agt = node.data?.agent as FlowAgentDetail | undefined;
		if (!agt) return '#2a2a30';
		if (agt.trigger_summary) return '#00e5ff';
		return '#c8ff00';
	}
</script>

<div style:width="100%" style:height="100%">
	<SvelteFlow
		bind:nodes
		bind:edges
		{nodeTypes}
		{onnodeclick}
		{onnodedragstop}
		initialViewport={{ x: 20, y: 10, zoom: 1 }}
		colorMode="dark"
		nodesConnectable={false}
		deleteKey=""
		proOptions={{ hideAttribution: true }}
		minZoom={0.1}
		maxZoom={2}
	>
		<Background gap={24} size={1} />
		<Controls showInteractive={false} />
		<MiniMap nodeColor={minimapNodeColor} pannable zoomable />

		<Panel position="bottom-left">
			<button
				class="flex items-center gap-1.5 border border-edge bg-surface-0/90 px-3 py-1.5 font-mono text-[11px] text-fg-faint backdrop-blur-sm transition-[color,background-color] duration-150 hover:bg-surface-2 hover:text-fg-muted"
				onclick={() => {
					clearSavedPositions();
					const fresh = buildGraph(detail.agents);
					nodes = fresh.nodes;
					edges = fresh.edges;
				}}
			>
				<RotateCcw size={12} strokeWidth={1.5} />
				Auto-arrange
			</button>
		</Panel>
	</SvelteFlow>
</div>
