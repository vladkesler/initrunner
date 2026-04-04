<script lang="ts">
	import { onMount } from 'svelte';
	import { getMcpServerTools, callMcpTool } from '$lib/api/mcp';
	import type { McpServer, McpTool, McpPlaygroundResult } from '$lib/api/types';
	import { Skeleton } from '$lib/components/ui/skeleton';
	import { Play, Copy, Clock, Trash2 } from 'lucide-svelte';
	import { toast } from '$lib/stores/toast.svelte';

	let {
		servers,
		preSelectedServerId = null,
		preSelectedToolName = null
	}: {
		servers: McpServer[];
		preSelectedServerId?: string | null;
		preSelectedToolName?: string | null;
	} = $props();

	let selectedServerId = $state('');
	let selectedToolName = $state('');
	let tools = $state<McpTool[]>([]);
	let toolsLoading = $state(false);
	let executing = $state(false);
	let result = $state<McpPlaygroundResult | null>(null);
	let argValues = $state<Record<string, string>>({});

	// History stored in localStorage
	const HISTORY_KEY = 'mcp-playground-history';
	const MAX_HISTORY = 50;

	interface HistoryEntry {
		serverId: string;
		serverName: string;
		toolName: string;
		arguments: Record<string, unknown>;
		timestamp: string;
		success: boolean;
		durationMs: number;
	}

	let history = $state<HistoryEntry[]>([]);

	onMount(() => {
		try {
			const raw = localStorage.getItem(HISTORY_KEY);
			if (raw) history = JSON.parse(raw);
		} catch {
			/* ignore */
		}

		// Apply pre-selection from "Test" button
		if (preSelectedServerId) {
			selectedServerId = preSelectedServerId;
			loadTools(preSelectedServerId).then(() => {
				if (preSelectedToolName) {
					selectedToolName = preSelectedToolName;
				}
			});
		}
	});

	const selectedTool = $derived(tools.find((t) => t.name === selectedToolName));

	const inputProperties = $derived.by(() => {
		if (!selectedTool?.input_schema) return [];
		const props = (selectedTool.input_schema as Record<string, unknown>).properties as
			| Record<string, Record<string, unknown>>
			| undefined;
		if (!props) return [];
		const required = new Set(
			((selectedTool.input_schema as Record<string, unknown>).required as string[]) ?? []
		);
		return Object.entries(props).map(([name, schema]) => ({
			name,
			type: (schema.type as string) ?? 'string',
			description: (schema.description as string) ?? '',
			required: required.has(name),
			enum: (schema.enum as string[]) ?? null
		}));
	});

	async function loadTools(serverId: string) {
		toolsLoading = true;
		selectedToolName = '';
		argValues = {};
		result = null;
		try {
			tools = await getMcpServerTools(serverId);
		} catch {
			tools = [];
		} finally {
			toolsLoading = false;
		}
	}

	function onServerChange(e: Event) {
		const val = (e.target as HTMLSelectElement).value;
		selectedServerId = val;
		if (val) loadTools(val);
	}

	function onToolChange(e: Event) {
		selectedToolName = (e.target as HTMLSelectElement).value;
		argValues = {};
		result = null;
	}

	function buildArguments(): Record<string, unknown> {
		const args: Record<string, unknown> = {};
		for (const prop of inputProperties) {
			const raw = argValues[prop.name];
			if (raw === undefined || raw === '') continue;
			if (prop.type === 'integer') args[prop.name] = parseInt(raw, 10);
			else if (prop.type === 'number') args[prop.name] = parseFloat(raw);
			else if (prop.type === 'boolean') args[prop.name] = raw === 'true';
			else args[prop.name] = raw;
		}
		return args;
	}

	async function execute() {
		if (!selectedServerId || !selectedToolName) return;
		executing = true;
		result = null;
		const args = buildArguments();
		try {
			result = await callMcpTool({
				server_id: selectedServerId,
				tool_name: selectedToolName,
				arguments: args
			});

			// Add to history
			const serverName =
				servers.find((s) => s.server_id === selectedServerId)?.display_name ?? selectedServerId;
			const entry: HistoryEntry = {
				serverId: selectedServerId,
				serverName,
				toolName: selectedToolName,
				arguments: args,
				timestamp: new Date().toISOString(),
				success: result.success,
				durationMs: result.duration_ms
			};
			history = [entry, ...history.slice(0, MAX_HISTORY - 1)];
			try {
				localStorage.setItem(HISTORY_KEY, JSON.stringify(history));
			} catch {
				/* ignore */
			}
		} catch (err) {
			result = {
				tool_name: selectedToolName,
				output: '',
				duration_ms: 0,
				success: false,
				error: String(err)
			};
		} finally {
			executing = false;
		}
	}

	function replayHistory(entry: HistoryEntry) {
		result = null;
		argValues = {};
		for (const [k, v] of Object.entries(entry.arguments)) {
			argValues[k] = String(v);
		}

		if (selectedServerId === entry.serverId && tools.length > 0) {
			// Same server, tools already loaded -- just switch tool
			selectedToolName = entry.toolName;
		} else {
			// Different server -- need to load tools
			selectedServerId = entry.serverId;
			selectedToolName = '';
			loadTools(entry.serverId).then(() => {
				selectedToolName = entry.toolName;
			});
		}
	}

	function clearHistory() {
		history = [];
		try {
			localStorage.removeItem(HISTORY_KEY);
		} catch {
			/* ignore */
		}
	}

	function copyResult() {
		if (result?.output) {
			navigator.clipboard.writeText(result.output);
			toast.success('Copied to clipboard');
		}
	}
</script>

<div class="flex gap-4" style="height: calc(100vh - 220px)">
	<!-- Main panel -->
	<div class="flex min-w-0 flex-1 flex-col gap-4">
		<!-- Pickers -->
		<div class="flex gap-3">
			<select
				class="h-9 min-w-0 flex-1 border border-edge bg-surface-1 px-3 font-mono text-[13px] text-fg focus:border-accent-primary-dim/60 focus:outline-none"
				value={selectedServerId}
				onchange={onServerChange}
			>
				<option value="">Select server...</option>
				{#each servers as s}
					<option value={s.server_id}>{s.display_name}</option>
				{/each}
			</select>

			<select
				class="h-9 min-w-0 flex-1 border border-edge bg-surface-1 px-3 font-mono text-[13px] text-fg focus:border-accent-primary-dim/60 focus:outline-none"
				value={selectedToolName}
				onchange={onToolChange}
				disabled={!selectedServerId || toolsLoading}
			>
				<option value="">{toolsLoading ? 'Loading...' : 'Select tool...'}</option>
				{#each tools as t}
					<option value={t.name}>{t.name}</option>
				{/each}
			</select>
		</div>

		<!-- Arguments form -->
		{#if selectedTool && inputProperties.length > 0}
			<div class="flex flex-col gap-2 border border-edge bg-surface-1 p-4">
				<div class="section-label mb-1" style="font-size: 10px; letter-spacing: 0.14em">
					ARGUMENTS
				</div>
				{#each inputProperties as prop}
					<div class="flex items-start gap-3">
						<label
							class="w-36 shrink-0 pt-1.5 font-mono text-[12px] text-fg-muted"
							for="arg-{prop.name}"
						>
							{prop.name}{#if prop.required}<span class="text-fail">*</span>{/if}
						</label>
						{#if prop.enum}
							<select
								id="arg-{prop.name}"
								class="h-8 min-w-0 flex-1 border border-edge bg-surface-05 px-2 font-mono text-[12px] text-fg focus:border-accent-primary-dim/60 focus:outline-none"
								value={argValues[prop.name] ?? ''}
								onchange={(e) => (argValues[prop.name] = (e.target as HTMLSelectElement).value)}
							>
								<option value=""></option>
								{#each prop.enum as v}
									<option value={v}>{v}</option>
								{/each}
							</select>
						{:else if prop.type === 'boolean'}
							<select
								id="arg-{prop.name}"
								class="h-8 w-24 border border-edge bg-surface-05 px-2 font-mono text-[12px] text-fg focus:border-accent-primary-dim/60 focus:outline-none"
								value={argValues[prop.name] ?? ''}
								onchange={(e) => (argValues[prop.name] = (e.target as HTMLSelectElement).value)}
							>
								<option value=""></option>
								<option value="true">true</option>
								<option value="false">false</option>
							</select>
						{:else}
							<input
								id="arg-{prop.name}"
								type={prop.type === 'integer' || prop.type === 'number' ? 'number' : 'text'}
								placeholder={prop.description}
								class="h-8 min-w-0 flex-1 border border-edge bg-surface-05 px-2 font-mono text-[12px] text-fg placeholder:text-fg-faint focus:border-accent-primary-dim/60 focus:outline-none"
								value={argValues[prop.name] ?? ''}
								oninput={(e) => (argValues[prop.name] = (e.target as HTMLInputElement).value)}
							/>
						{/if}
					</div>
				{/each}
			</div>
		{/if}

		<!-- Execute button -->
		<button
			class="flex h-9 w-fit items-center gap-2 rounded-[2px] bg-accent-primary px-4 font-medium text-surface-0 transition-colors hover:bg-accent-primary-hover disabled:opacity-50"
			onclick={execute}
			disabled={!selectedServerId || !selectedToolName || executing}
		>
			<Play size={14} />
			{executing ? 'Executing...' : 'Execute'}
		</button>

		<!-- Response -->
		{#if result}
			<div class="flex flex-col gap-2">
				<div class="flex items-center gap-2">
					<span
						class="status-dot"
						style="background: {result.success ? 'var(--color-ok)' : 'var(--color-fail)'}"
					></span>
					<span class="font-mono text-[12px] text-fg-muted">
						{result.success ? 'Success' : 'Error'}
					</span>
					<span
						class="flex items-center gap-1 rounded-full border border-edge px-2 py-0.5 font-mono text-[11px] text-fg-faint"
					>
						<Clock size={10} />
						{result.duration_ms}ms
					</span>
					{#if result.output}
						<button
							class="ml-auto flex items-center gap-1 rounded-[2px] border border-edge px-2 py-0.5 text-[11px] text-fg-faint transition-colors hover:border-accent-primary-dim hover:text-fg-muted"
							onclick={copyResult}
						>
							<Copy size={10} />
							Copy
						</button>
					{/if}
				</div>
				<pre
					class="max-h-80 overflow-auto border border-edge bg-surface-05 p-4 font-mono text-[12px] text-fg-muted"
				>{result.error ?? result.output}</pre>
			</div>
		{/if}
	</div>

	<!-- History sidebar -->
	<div
		class="flex w-64 shrink-0 flex-col border-l border-edge pl-4"
	>
		<div class="mb-2 flex items-center justify-between">
			<span class="section-label" style="font-size: 10px; letter-spacing: 0.14em">HISTORY</span>
			{#if history.length > 0}
				<button
					class="text-fg-faint transition-colors hover:text-fail"
					onclick={clearHistory}
					title="Clear history"
				>
					<Trash2 size={12} />
				</button>
			{/if}
		</div>

		<div class="flex flex-1 flex-col gap-1 overflow-y-auto">
			{#if history.length === 0}
				<p class="text-[12px] text-fg-faint">No calls yet.</p>
			{:else}
				{#each history as entry, i}
					<button
						type="button"
						class="flex flex-col gap-0.5 border-b border-edge-ghost px-2 py-2 text-left transition-colors hover:bg-surface-1"
						onclick={() => { replayHistory(entry); }}
					>
						<div class="flex items-center gap-1.5">
							<span
								class="status-dot"
								style="background: {entry.success ? 'var(--color-ok)' : 'var(--color-fail)'}"
							></span>
							<span class="truncate font-mono text-[11px] text-fg">{entry.toolName}</span>
						</div>
						<span class="truncate font-mono text-[10px] text-fg-faint">
							{entry.serverName}
						</span>
						<span class="text-[10px] text-fg-faint">
							{entry.durationMs}ms
						</span>
					</button>
				{/each}
			{/if}
		</div>
	</div>
</div>
