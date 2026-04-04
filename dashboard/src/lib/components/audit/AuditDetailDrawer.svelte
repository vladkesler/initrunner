<script lang="ts">
	import type { AuditRecord } from '$lib/api/types';
	import { X, CheckCircle, XCircle, Copy } from 'lucide-svelte';

	let { record, onClose }: { record: AuditRecord; onClose: () => void } = $props();

	let copyFeedback = $state('');

	function formatTimestamp(ts: string): string {
		try {
			return new Date(ts).toLocaleString();
		} catch {
			return ts;
		}
	}

	async function copyText(text: string) {
		try {
			await navigator.clipboard.writeText(text);
			copyFeedback = 'Copied!';
			setTimeout(() => (copyFeedback = ''), 1500);
		} catch {
			// Clipboard not available
		}
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Escape') onClose();
	}
</script>

<svelte:window onkeydown={handleKeydown} />

<!-- Backdrop -->
<!-- svelte-ignore a11y_no_static_element_interactions -->
<div class="fixed inset-0 z-40 bg-black/40" onclick={onClose} onkeydown={(e) => e.key === 'Escape' && onClose()}></div>

<!-- Drawer panel -->
<div class="fixed inset-y-0 right-0 z-50 flex w-full max-w-lg flex-col border-l border-edge bg-surface-0 shadow-2xl">
	<!-- Header -->
	<div class="flex items-center justify-between border-b border-edge px-5 py-4">
		<div class="flex items-center gap-3">
			{#if record.success}
				<CheckCircle size={16} class="text-ok" />
			{:else}
				<XCircle size={16} class="text-fail" />
			{/if}
			<h2 class="text-[14px] font-semibold text-fg">Run Detail</h2>
		</div>
		<button
			class="p-1 text-fg-faint transition-[color] duration-150 hover:text-fg"
			onclick={onClose}
			aria-label="Close"
		>
			<X size={16} />
		</button>
	</div>

	<!-- Content -->
	<div class="flex-1 overflow-y-auto p-5">
		<div class="space-y-5">
			<!-- Metadata grid -->
			<div class="grid grid-cols-2 gap-3">
				<div>
					<div class="mb-1 section-label">Agent</div>
					<div class="font-mono text-[13px] text-fg-muted">{record.agent_name}</div>
				</div>
				<div>
					<div class="mb-1 section-label">Model</div>
					<div class="font-mono text-[13px] text-fg-muted">{record.model}</div>
				</div>
				<div>
					<div class="mb-1 section-label">Provider</div>
					<div class="font-mono text-[13px] text-fg-muted">{record.provider}</div>
				</div>
				<div>
					<div class="mb-1 section-label">Timestamp</div>
					<div class="font-mono text-[13px] text-fg-muted">{formatTimestamp(record.timestamp)}</div>
				</div>
				<div>
					<div class="mb-1 section-label">Tokens</div>
					<div class="font-mono text-[13px] text-fg-muted">
						{record.tokens_in.toLocaleString()} in / {record.tokens_out.toLocaleString()} out
					</div>
				</div>
				<div>
					<div class="mb-1 section-label">Duration</div>
					<div class="font-mono text-[13px] text-fg-muted">{record.duration_ms.toLocaleString()}ms</div>
				</div>
				<div>
					<div class="mb-1 section-label">Tool Calls</div>
					<div class="font-mono text-[13px] text-fg-muted">{record.tool_calls}</div>
				</div>
				{#if record.trigger_type}
					<div>
						<div class="mb-1 section-label">Trigger</div>
						<div class="font-mono text-[13px] text-fg-muted">{record.trigger_type}</div>
					</div>
				{/if}
			</div>

			<!-- Run ID -->
			<div>
				<div class="mb-1 section-label">Run ID</div>
				<div class="flex items-center gap-2">
					<code class="font-mono text-[13px] text-fg-faint">{record.run_id}</code>
					<button
						class="text-fg-faint transition-[color] duration-150 hover:text-fg-muted"
						onclick={() => copyText(record.run_id)}
						aria-label="Copy run ID"
					>
						<Copy size={12} />
					</button>
					{#if copyFeedback}
						<span class="text-[13px] text-ok">{copyFeedback}</span>
					{/if}
				</div>
			</div>

			<!-- Error -->
			{#if record.error}
				<div>
					<div class="mb-1 section-label text-fail">Error</div>
					<pre class="overflow-x-auto border border-fail/20 bg-fail/5 p-3 font-mono text-[13px] leading-relaxed text-fail">{record.error}</pre>
				</div>
			{/if}

			<!-- Prompt -->
			<div>
				<div class="mb-2 flex items-center justify-between">
					<div class="section-label">Prompt</div>
					<button
						class="text-[13px] text-fg-faint transition-[color] duration-150 hover:text-fg-muted"
						onclick={() => copyText(record.user_prompt)}
					>
						Copy
					</button>
				</div>
				<pre class="max-h-48 overflow-y-auto border border-edge bg-surface-1 p-3 font-mono text-[13px] leading-relaxed text-fg-muted whitespace-pre-wrap">{record.user_prompt}</pre>
			</div>

			<!-- Output -->
			<div>
				<div class="mb-2 flex items-center justify-between">
					<div class="section-label">Output</div>
					<button
						class="text-[13px] text-fg-faint transition-[color] duration-150 hover:text-fg-muted"
						onclick={() => copyText(record.output)}
					>
						Copy
					</button>
				</div>
				<pre class="max-h-96 overflow-y-auto border border-edge bg-surface-1 p-3 font-mono text-[13px] leading-relaxed text-fg-muted whitespace-pre-wrap">{record.output}</pre>
			</div>
		</div>
	</div>
</div>
