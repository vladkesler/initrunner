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
	import { goto } from '$app/navigation';
	import type { McpServer, McpAgentRef } from '$lib/api/types';
	import McpServerNode from './McpServerNode.svelte';
	import McpAgentNode from './McpAgentNode.svelte';
	import { safeGet, safeSet } from '$lib/utils/storage';
	import { RotateCcw, Copy } from 'lucide-svelte';
	import { toast } from '$lib/stores/toast.svelte';

	let { servers }: { servers: McpServer[] } = $props();

	const TIER_PITCH = 400;
	const NODE_PITCH = 160;
	const OFFSET_X = 60;
	const OFFSET_Y = 60;

	const storageKey = 'mcp-canvas-positions';

	function loadSavedPositions(): Record<string, { x: number; y: number }> {
		const raw = safeGet(storageKey);
		if (!raw) return {};
		try {
			return JSON.parse(raw);
		} catch {
			return {};
		}
	}

	function savePosition(id: string, pos: { x: number; y: number }) {
		const saved = loadSavedPositions();
		saved[id] = { x: Math.round(pos.x), y: Math.round(pos.y) };
		safeSet(storageKey, JSON.stringify(saved));
	}

	function clearSavedPositions() {
		safeSet(storageKey, '');
	}

	function buildGraph(srvs: McpServer[]): { nodes: Node[]; edges: Edge[] } {
		const savedPositions = loadSavedPositions();

		// Tier 0: server nodes
		const serverNodes: Node[] = srvs.map((srv, i) => ({
			id: `srv-${srv.server_id}`,
			type: 'mcpServer',
			position: savedPositions[`srv-${srv.server_id}`] ?? {
				x: OFFSET_X,
				y: OFFSET_Y + i * NODE_PITCH
			},
			data: { server: srv },
			connectable: false
		}));

		// Tier 1: deduplicated agent nodes
		const agentMap = new Map<string, McpAgentRef>();
		for (const srv of srvs) {
			for (const ref of srv.agent_refs) {
				if (!agentMap.has(ref.agent_id)) {
					agentMap.set(ref.agent_id, ref);
				}
			}
		}

		const agentNodes: Node[] = [...agentMap.entries()].map(([id, ref], i) => ({
			id: `agt-${id}`,
			type: 'mcpAgent',
			position: savedPositions[`agt-${id}`] ?? {
				x: OFFSET_X + TIER_PITCH,
				y: OFFSET_Y + i * NODE_PITCH
			},
			data: { agent: ref },
			connectable: false
		}));

		// Edges: server -> agent
		const edges: Edge[] = srvs.flatMap((srv) =>
			srv.agent_refs.map((ref) => ({
				id: `edge-${srv.server_id}-${ref.agent_id}`,
				source: `srv-${srv.server_id}`,
				target: `agt-${ref.agent_id}`,
				type: 'default',
				animated: true,
				style: 'stroke: oklch(0.91 0.20 128); stroke-width: 2px;'
			}))
		);

		return { nodes: [...serverNodes, ...agentNodes], edges };
	}

	const nodeTypes = { mcpServer: McpServerNode, mcpAgent: McpAgentNode };
	// svelte-ignore state_referenced_locally
	const initial = buildGraph(servers);
	let nodes = $state.raw<Node[]>(initial.nodes);
	let edges = $state.raw<Edge[]>(initial.edges);

	let lastClickTime = $state(0);

	function onnodeclick(_event: MouseEvent, node: Node) {
		const now = Date.now();
		if (now - lastClickTime < 400) {
			const agentRef = node.data?.agent as McpAgentRef | undefined;
			if (agentRef?.agent_id) {
				goto(`/agents/${agentRef.agent_id}`);
			}
		}
		lastClickTime = now;
	}

	function onnodedragstop(_event: MouseEvent, node: Node) {
		savePosition(node.id, node.position);
	}

	function minimapNodeColor(node: Node): string {
		if (node.id.startsWith('srv-')) return '#00e5ff';
		return '#c8ff00';
	}

	function exportYaml() {
		const lines: string[] = ['tools:'];
		for (const srv of servers) {
			lines.push(`  - type: mcp`);
			lines.push(`    transport: ${srv.transport}`);
			if (srv.command) {
				lines.push(`    command: ${srv.command}`);
				if (srv.args.length > 0) {
					lines.push(`    args:`);
					for (const a of srv.args) lines.push(`      - "${a}"`);
				}
			}
			if (srv.url) {
				lines.push(`    url: ${srv.url}`);
			}
			lines.push('');
		}
		navigator.clipboard.writeText(lines.join('\n'));
		toast.success('YAML exported to clipboard');
	}
</script>

{#if servers.length === 0}
	<div class="flex h-full items-center justify-center text-[13px] text-fg-faint">
		No MCP servers configured. Add tool configs with type: mcp to see the topology.
	</div>
{:else}
	<div style:width="100%" style:height="calc(100vh - 220px)">
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
				<div class="flex gap-2">
					<button
						class="flex items-center gap-1.5 border border-edge bg-surface-0/90 px-3 py-1.5 font-mono text-[11px] text-fg-faint backdrop-blur-sm transition-[color,background-color] duration-150 hover:bg-surface-2 hover:text-fg-muted"
						onclick={() => {
							clearSavedPositions();
							const fresh = buildGraph(servers);
							nodes = fresh.nodes;
							edges = fresh.edges;
						}}
					>
						<RotateCcw size={12} strokeWidth={1.5} />
						Auto-arrange
					</button>
					<button
						class="flex items-center gap-1.5 border border-edge bg-surface-0/90 px-3 py-1.5 font-mono text-[11px] text-fg-faint backdrop-blur-sm transition-[color,background-color] duration-150 hover:bg-surface-2 hover:text-fg-muted"
						onclick={exportYaml}
					>
						<Copy size={12} strokeWidth={1.5} />
						Export YAML
					</button>
				</div>
			</Panel>
		</SvelteFlow>
	</div>
{/if}
