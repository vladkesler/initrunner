<script lang="ts">
	import { streamRun } from '$lib/api/runs';
	import type {
		ApprovalRequiredData,
		CostUpdateData,
		PendingCall,
		RunResponse,
		ThreadMessage,
		ToolEventData,
		UsageData
	} from '$lib/api/types';
	import ConversationThread from './ConversationThread.svelte';
	import ToolActivityPanel from './ToolActivityPanel.svelte';
	import TokenMeter from './TokenMeter.svelte';
	import { Play, Square, RotateCcw } from 'lucide-svelte';
	import ApprovalCardGroup from '$lib/components/approvals/ApprovalCardGroup.svelte';
	import { approvals } from '$lib/stores/approvals.svelte';
	import { startedRuns } from '$lib/stores/startedRuns.svelte';
	import { toast } from '$lib/stores/toast.svelte';

	let {
		agentId,
		agentName = 'Agent',
		onRunCompleted,
		blockedReason = null
	}: {
		agentId: string;
		agentName?: string;
		onRunCompleted?: () => void;
		blockedReason?: string | null;
	} = $props();

	let prompt = $state('');
	let messages: ThreadMessage[] = $state([]);
	let messageHistory: string | null = $state(null);
	let running = $state(false);
	let controller: AbortController | null = $state(null);
	let requestVersion = $state(0);

	let toolEvents: ToolEventData[] = $state([]);
	let usage: UsageData | null = $state(null);
	let lastResult: RunResponse | null = $state(null);
	let costUpdate: CostUpdateData | null = $state(null);
	let pendingRun: { runId: string; calls: PendingCall[] } | null = $state(null);
	let approvalSubmitting = $state(false);

	function handleRun() {
		if (!prompt.trim() || running || blockedReason) return;

		const currentVersion = requestVersion;
		const userPrompt = prompt.trim();
		prompt = '';
		toolEvents = [];
		lastResult = null;
		costUpdate = null;
		pendingRun = null;

		messages = [
			...messages,
			{ role: 'user', content: userPrompt, status: 'complete', identityLabel: 'You' },
			{ role: 'assistant', content: '', status: 'streaming', identityLabel: agentName }
		];

		running = true;
		const assistantIdx = messages.length - 1;

		controller = streamRun(
			{ agent_id: agentId, prompt: userPrompt, message_history: messageHistory },
			{
				onToken(text) {
					if (requestVersion !== currentVersion) return;
					messages[assistantIdx] = {
						...messages[assistantIdx],
						content: messages[assistantIdx].content + text
					};
				},
				onToolEvent(event) {
					if (requestVersion !== currentVersion) return;
					toolEvents = [...toolEvents, event];
				},
				onUsage(u) {
					if (requestVersion !== currentVersion) return;
					usage = u;
				},
				onCostUpdate(data) {
					if (requestVersion !== currentVersion) return;
					costUpdate = data;
				},
				onResult(r: RunResponse) {
					if (requestVersion !== currentVersion) return;
					startedRuns.add(r.run_id);
					messages[assistantIdx] = {
						...messages[assistantIdx],
						status: 'complete',
						result: r
					};
					if (r.success && r.message_history) {
						messageHistory = r.message_history;
					}
					lastResult = r;
					running = false;
					controller = null;
					onRunCompleted?.();
				},
				onApprovalRequired(data: ApprovalRequiredData) {
					if (requestVersion !== currentVersion) return;
					startedRuns.add(data.run_id);
					approvals.bumpOnSseApproval(data.run_id, data.pending_approvals.length);
					if (data.message_history) {
						messageHistory = data.message_history;
					}
					pendingRun = { runId: data.run_id, calls: data.pending_approvals };
					messages[assistantIdx] = {
						...messages[assistantIdx],
						status: 'interrupted'
					};
					running = false;
					controller = null;
				},
				onError(err: string) {
					if (requestVersion !== currentVersion) return;
					messages[assistantIdx] = {
						...messages[assistantIdx],
						status: 'error',
						error: err
					};
					running = false;
					controller = null;
				}
			}
		);
	}

	async function handleApprovalSubmit(decisions: Record<string, boolean>): Promise<void> {
		if (!pendingRun) return;
		approvalSubmitting = true;
		try {
			const resp = await approvals.submit(pendingRun.runId, decisions);
			if (resp.status === 'paused') {
				// Re-paused — swap the card group in place.
				pendingRun = { runId: resp.run_id, calls: resp.pending_approvals };
				if (resp.message_history) messageHistory = resp.message_history;
				toast.info(`Run paused again (${resp.pending_approvals.length} new call(s))`);
			} else {
				if (resp.message_history) messageHistory = resp.message_history;
				const lastIdx = messages.length - 1;
				if (lastIdx >= 0 && messages[lastIdx].role === 'assistant') {
					messages[lastIdx] = {
						...messages[lastIdx],
						status: 'complete',
						content: resp.output || messages[lastIdx].content
					};
				}
				pendingRun = null;
				toast.success('Resumed.');
				onRunCompleted?.();
			}
		} catch (e) {
			if (!(e && typeof e === 'object' && 'status' in e && e.status === 404)) {
				toast.error(e instanceof Error ? e.message : String(e));
			}
			pendingRun = null;
		} finally {
			approvalSubmitting = false;
		}
	}

	function handleStop() {
		controller?.abort();
		controller = null;
		running = false;

		const lastIdx = messages.length - 1;
		if (lastIdx >= 0 && messages[lastIdx].role === 'assistant' && messages[lastIdx].status === 'streaming') {
			messages[lastIdx] = { ...messages[lastIdx], status: 'interrupted' };
		}
	}

	function handleNewConversation() {
		controller?.abort();
		controller = null;
		running = false;
		requestVersion++;
		messages = [];
		messageHistory = null;
		prompt = '';
		toolEvents = [];
		usage = null;
		lastResult = null;
		costUpdate = null;
		pendingRun = null;
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter' && (e.metaKey || e.ctrlKey) && !running) {
			e.preventDefault();
			handleRun();
		}
	}

	const isMac = typeof navigator !== 'undefined' && navigator.platform?.includes('Mac');
	const hasMessages = $derived(messages.length > 0);
	const showPanel = $derived(running || toolEvents.length > 0 || lastResult != null);
</script>

<div class="flex flex-1 flex-col gap-3">
	<ConversationThread {messages} />

	{#if pendingRun}
		<ApprovalCardGroup
			runId={pendingRun.runId}
			calls={pendingRun.calls}
			submitting={approvalSubmitting}
			onSubmit={handleApprovalSubmit}
		/>
	{/if}

	{#if showPanel}
		<div class="h-48 shrink-0">
			<ToolActivityPanel events={toolEvents} />
		</div>
		<TokenMeter {usage} result={lastResult} {running} {costUpdate} />
	{/if}

	<!-- Input area -->
	<div class="flex flex-col gap-1.5">
		{#if hasMessages}
			<div class="flex justify-end">
				<button
					class="flex items-center gap-1.5 px-2 py-1 font-mono text-[12px] text-fg-faint transition-colors duration-150 hover:text-fg-muted"
					onclick={handleNewConversation}
				>
					<RotateCcw size={12} />
					New conversation
				</button>
			</div>
		{/if}

		<div class="flex flex-col border border-edge bg-surface-1 transition-[border-color,box-shadow] duration-150 focus-within:border-accent-primary/40 focus-within:shadow-[0_0_0_3px_oklch(0.91_0.20_128/0.08)]">
			<textarea
				bind:value={prompt}
				placeholder="Enter a prompt..."
				class="w-full resize-none border-none bg-transparent p-3 font-mono text-[13px] text-fg outline-none placeholder:text-fg-faint"
				style="min-height: 80px"
				onkeydown={handleKeydown}
				disabled={running || !!blockedReason}
			></textarea>
			<div class="flex items-center justify-between border-t border-edge-subtle px-3 py-1.5">
				<span class="font-mono text-[12px] text-fg-faint">{isMac ? 'Cmd' : 'Ctrl'}+Enter to run</span>
				{#if running}
					<button
						class="flex h-7 w-7 items-center justify-center rounded-full border border-edge bg-surface-2 text-fail transition-[border-color,background-color] duration-150 hover:border-fail/40 hover:bg-fail/5"
						onclick={handleStop}
						aria-label="Stop"
					>
						<Square size={14} fill="currentColor" />
					</button>
				{:else}
					<button
						class="flex h-7 w-7 items-center justify-center rounded-full border border-edge bg-surface-2 text-accent-primary transition-[border-color,background-color] duration-150 hover:border-accent-primary/40 hover:bg-accent-primary/5 disabled:opacity-30 disabled:pointer-events-none"
						onclick={handleRun}
						disabled={!prompt.trim() || !!blockedReason}
						aria-label="Run"
					>
						<Play size={14} fill="currentColor" />
					</button>
				{/if}
			</div>
		</div>
	</div>
</div>
