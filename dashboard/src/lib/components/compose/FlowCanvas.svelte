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
	import type { ComposeDetail, ComposeServiceDetail } from '$lib/api/types';
	import ServiceNode from './ServiceNode.svelte';
	import { safeGet, safeSet } from '$lib/utils/storage';
	import { RotateCcw } from 'lucide-svelte';

	let {
		detail,
		onServiceClick
	}: {
		detail: ComposeDetail;
		onServiceClick?: (name: string) => void;
	} = $props();

	// ── Layout constants ──────────────────────────────────────────────
	const TIER_PITCH = 320;
	const NODE_PITCH = 140;
	const OFFSET_X = 60;
	const OFFSET_Y = 60;

	const storageKey = $derived(`compose-node-positions-${detail.id}`);

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

	// ── Topological tiering ───────────────────────────────────────────

	/** Kahn's algorithm: assign tier indices based on edges. */
	function computeTiers(
		services: ComposeServiceDetail[],
		edgeFn: (svc: ComposeServiceDetail) => string[]
	): Map<string, number> {
		const names = new Set(services.map((s) => s.name));
		const inDegree = new Map<string, number>();
		const adj = new Map<string, string[]>();
		for (const name of names) {
			inDegree.set(name, 0);
			adj.set(name, []);
		}

		for (const svc of services) {
			// edgeFn returns what this service depends on / receives from
			for (const dep of edgeFn(svc)) {
				if (names.has(dep)) {
					adj.get(dep)!.push(svc.name);
					inDegree.set(svc.name, (inDegree.get(svc.name) ?? 0) + 1);
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

	function buildLayout(services: ComposeServiceDetail[]): Map<string, number> {
		// Primary: tier by depends_on
		const depTiers = computeTiers(services, (svc) => svc.depends_on);

		// If depends_on produces a single tier, fall back to sink.targets
		const maxTier = Math.max(...depTiers.values(), 0);
		if (maxTier === 0 && services.length > 1) {
			// All in tier 0 -- try sink targets as reverse edges
			const sinkTiers = computeTiers(services, (svc) =>
				// Sink targets mean "I send to these" -- so for tiering,
				// a service that receives (is a target) depends on the sender.
				// We want senders in earlier tiers, so we invert: if X sends to Y,
				// Y's "dependency" is X. But our edgeFn returns what svc depends on.
				// So for each service, find who sends TO it.
				services
					.filter((s) => s.sink?.targets.includes(svc.name))
					.map((s) => s.name)
			);
			return sinkTiers;
		}

		return depTiers;
	}

	// ── Build nodes & edges ───────────────────────────────────────────

	function buildGraph(svcs: ComposeServiceDetail[]): { nodes: Node[]; edges: Edge[] } {
		const tiers = buildLayout(svcs);
		const savedPositions = loadSavedPositions();

		// Group by tier for vertical stacking
		const tierGroups = new Map<number, ComposeServiceDetail[]>();
		for (const svc of svcs) {
			const t = tiers.get(svc.name) ?? 0;
			if (!tierGroups.has(t)) tierGroups.set(t, []);
			tierGroups.get(t)!.push(svc);
		}

		const nodes: Node[] = [];
		for (const [tier, group] of tierGroups) {
			for (let i = 0; i < group.length; i++) {
				const svc = group[i];
				const saved = savedPositions[svc.name];
				nodes.push({
					id: svc.name,
					type: 'composeService',
					position: saved ?? {
						x: OFFSET_X + tier * TIER_PITCH,
						y: OFFSET_Y + i * NODE_PITCH
					},
					data: { service: svc },
					connectable: false
				});
			}
		}

		const edges: Edge[] = [];

		// Delegation edges (solid, lime)
		for (const svc of svcs) {
			if (!svc.sink) continue;
			for (const target of svc.sink.targets) {
				const label = svc.sink.strategy !== 'all' ? svc.sink.strategy : undefined;
				edges.push({
					id: `delegate-${svc.name}-${target}`,
					source: svc.name,
					target,
					type: 'default',
					animated: true,
					label,
					style: 'stroke: oklch(0.91 0.20 128); stroke-width: 2px;',
					labelStyle: 'fill: oklch(0.91 0.20 128); font-size: 10px; font-family: var(--font-mono);'
				});
			}
		}

		// Dependency edges (dashed, muted): dep -> service
		// Skip when a delegation edge already covers the same pair
		const delegateKeys = new Set(
			edges.filter((e) => e.id.startsWith('delegate-')).map((e) => `${e.source}->${e.target}`)
		);
		for (const svc of svcs) {
			for (const dep of svc.depends_on) {
				if (delegateKeys.has(`${dep}->${svc.name}`)) continue;
				edges.push({
					id: `dep-${dep}-${svc.name}`,
					source: dep,
					target: svc.name,
					type: 'smoothstep',
					animated: false,
					style: 'stroke: oklch(0.50 0.02 260); stroke-width: 1px; stroke-dasharray: 5 3;'
				});
			}
		}

		return { nodes, edges };
	}

	// ── State ─────────────────────────────────────────────────────────

	const nodeTypes = { composeService: ServiceNode };
	// svelte-ignore state_referenced_locally
	const initial = buildGraph(detail.services);
	let nodes = $state.raw<Node[]>(initial.nodes);
	let edges = $state.raw<Edge[]>(initial.edges);

	// ── Events ────────────────────────────────────────────────────────

	let lastClickTime = $state(0);

	function onnodeclick(_event: MouseEvent, node: Node) {
		const now = Date.now();
		const svc = node.data?.service as ComposeServiceDetail | undefined;
		if (!svc) return;

		if (now - lastClickTime < 400 && svc.agent_id) {
			// Double click -> navigate to agent
			goto(`/agents/${svc.agent_id}`);
		} else {
			onServiceClick?.(svc.name);
		}
		lastClickTime = now;
	}

	function onnodedragstop(_event: MouseEvent, node: Node) {
		savePosition(node.id, node.position);
	}

	function minimapNodeColor(node: Node): string {
		const svc = node.data?.service as ComposeServiceDetail | undefined;
		if (!svc) return '#2a2a30';
		if (svc.trigger_summary) return '#00e5ff';
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
					const fresh = buildGraph(detail.services);
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
