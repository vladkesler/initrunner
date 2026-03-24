<script lang="ts">
	import { untrack } from 'svelte';
	import {
		SvelteFlow,
		Background,
		Controls,
		MiniMap,
		Panel,
		type Node,
		type Edge,
	} from '@xyflow/svelte';
	import '@xyflow/svelte/dist/style.css';
	import { goto } from '$app/navigation';
	import type { AgentSummary } from '$lib/api/types';
	import AgentNode from './AgentNode.svelte';
	import CategoryLabel from './CategoryLabel.svelte';
	import { safeGet, safeSet } from '$lib/utils/storage';
	import { RotateCcw } from 'lucide-svelte';

	let {
		agents,
		dimmedIds = new Set<string>(),
	}: {
		agents: AgentSummary[];
		dimmedIds?: Set<string>;
	} = $props();

	// ── Categories & layout ───────────────────────────────────────────

	const CATEGORIES = [
		{ key: 'errored', label: 'Errored', icon: 'AlertTriangle', test: (a: AgentSummary) => a.error !== null },
		{ key: 'reactive', label: 'Reactive', icon: 'Zap', test: (a: AgentSummary) => a.features.includes('triggers') },
		{ key: 'intelligence', label: 'Intelligence', icon: 'BookOpen', test: (a: AgentSummary) => a.features.includes('ingest') || a.features.includes('memory') },
		{ key: 'connected', label: 'Connected', icon: 'Plug', test: (a: AgentSummary) => a.features.includes('sinks') },
		{ key: 'skilled', label: 'Skilled', icon: 'Sparkles', test: (a: AgentSummary) => a.features.includes('skills') },
		{ key: 'equipped', label: 'Equipped', icon: 'Wrench', test: (a: AgentSummary) => a.features.includes('tools') },
		{ key: 'bare', label: 'Other', icon: 'Box', test: () => true },
	] as const;

	const STORAGE_KEY = 'agent-node-positions';
	const COLS = 5;
	const COL_PITCH = 264;
	const ROW_PITCH = 120;
	const SECTION_GAP = 100;
	const LABEL_H = 44;

	function loadSavedPositions(): Record<string, { x: number; y: number }> {
		const raw = safeGet(STORAGE_KEY);
		if (!raw) return {};
		try { return JSON.parse(raw); } catch { return {}; }
	}

	function savePosition(id: string, pos: { x: number; y: number }) {
		const saved = loadSavedPositions();
		saved[id] = { x: Math.round(pos.x), y: Math.round(pos.y) };
		safeSet(STORAGE_KEY, JSON.stringify(saved));
	}

	function clearSavedPositions() {
		safeSet(STORAGE_KEY, '');
	}

	function categorizeAgents(agentList: AgentSummary[]): Map<string, AgentSummary[]> {
		const groups = new Map<string, AgentSummary[]>();
		const assigned = new Set<string>();
		for (const cat of CATEGORIES) groups.set(cat.key, []);
		for (const agent of agentList) {
			for (const cat of CATEGORIES) {
				if (!assigned.has(agent.id) && cat.test(agent)) {
					groups.get(cat.key)!.push(agent);
					assigned.add(agent.id);
					break;
				}
			}
		}
		for (const [key, val] of groups) {
			if (val.length === 0) groups.delete(key);
		}
		return groups;
	}

	function buildNodes(agentList: AgentSummary[]): Node[] {
		const groups = categorizeAgents(agentList);
		const savedPositions = loadSavedPositions();
		const result: Node[] = [];
		let cursorY = 0;

		for (const [catKey, catAgents] of groups) {
			const catDef = CATEGORIES.find((c) => c.key === catKey)!;

			result.push({
				id: `label-${catKey}`,
				type: 'categoryLabel',
				position: { x: 0, y: cursorY },
				data: { label: catDef.label, icon: catDef.icon, count: catAgents.length },
				draggable: false,
				selectable: false,
				connectable: false,
			});

			cursorY += LABEL_H;

			for (let i = 0; i < catAgents.length; i++) {
				const col = i % COLS;
				const row = Math.floor(i / COLS);
				const agent = catAgents[i];
				const saved = savedPositions[agent.id];
				result.push({
					id: agent.id,
					type: 'agent',
					position: saved ?? { x: col * COL_PITCH, y: cursorY + row * ROW_PITCH },
					data: { agent },
					connectable: false,
				});
			}

			const rows = Math.ceil(catAgents.length / COLS);
			cursorY += rows * ROW_PITCH + SECTION_GAP;
		}

		return result;
	}

	// ── State ─────────────────────────────────────────────────────────

	const nodeTypes = { agent: AgentNode, categoryLabel: CategoryLabel };
	// svelte-ignore state_referenced_locally
	let nodes = $state.raw<Node[]>(buildNodes(agents));
	let edges = $state.raw<Edge[]>([]);

	// ── Dimming from parent filter ────────────────────────────────────

	$effect(() => {
		const ids = dimmedIds;
		const current = untrack(() => nodes);
		if (current.length === 0) return;
		nodes = current.map((n) => {
			if (n.type === 'categoryLabel') return n;
			const cls = ids.size > 0 && ids.has(n.id) ? 'dimmed' : '';
			return n.class === cls ? n : { ...n, class: cls };
		});
	});

	// ── Events ────────────────────────────────────────────────────────

	function onnodeclick(_event: MouseEvent, node: Node) {
		if (node.type === 'categoryLabel') return;
		goto(`/agents/${node.id}`);
	}

	function onnodedragstop(_event: MouseEvent, node: Node) {
		if (node.type === 'categoryLabel') return;
		savePosition(node.id, node.position);
	}

	function minimapNodeColor(node: Node): string {
		if (node.type === 'categoryLabel') return 'transparent';
		const agent = node.data?.agent as AgentSummary | undefined;
		if (!agent) return '#2a2a30';
		if (agent.error) return '#ff4d6a';
		if (agent.features.includes('triggers')) return '#00e5ff';
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
				onclick={() => { clearSavedPositions(); nodes = buildNodes(agents); }}
			>
				<RotateCcw size={12} strokeWidth={1.5} />
				Auto-arrange
			</button>
		</Panel>
	</SvelteFlow>
</div>
