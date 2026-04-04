<script lang="ts">
	import { streamFlowRun } from '$lib/api/flow';
	import type {
		FlowRunResponse,
		FlowThreadMessage,
		FlowDetail,
		AgentStepResponse,
		ThreadMessage
	} from '$lib/api/types';
	import ConversationThread from '$lib/components/runs/ConversationThread.svelte';
	import AgentTrace from './AgentTrace.svelte';
	import PipelineStepper from './PipelineStepper.svelte';
	import SeedAvatar from '$lib/components/ui/SeedAvatar.svelte';
	import { Play, Square, RotateCcw } from 'lucide-svelte';

	let {
		flowId,
		detail,
		onRunCompleted
	}: {
		flowId: string;
		detail: FlowDetail;
		onRunCompleted?: () => void;
	} = $props();

	let prompt = $state('');
	let messages: FlowThreadMessage[] = $state([]);
	let messageHistory: string | null = $state(null);
	let running = $state(false);
	let controller: AbortController | null = $state(null);
	let requestVersion = $state(0);

	// Pipeline progress tracking
	let completedAgents = $state<string[]>([]);
	let activeAgents = $state(new Set<string>());
	let flowStart = $state(0);
	let flowElapsed = $state(0);
	let flowTimer: ReturnType<typeof setInterval> | null = null;

	const totalAgents = $derived(detail.agents.length);

	/** Adapt FlowThreadMessage[] to ThreadMessage[] for ConversationThread. */
	const threadMessages = $derived<ThreadMessage[]>(
		messages.map((m) => {
			const base: ThreadMessage = {
				role: m.role,
				content: m.content,
				status: m.status,
				error: m.error,
				identityLabel: m.role === 'user' ? 'You' : (m.activeAgent ?? 'Flow')
			};
			if (m.result) {
				base.result = {
					tokens_in: m.result.tokens_in,
					tokens_out: m.result.tokens_out,
					duration_ms: m.result.duration_ms,
					tool_calls: m.result.steps.reduce((sum, s) => sum + s.tool_calls, 0),
					tool_call_names: [...new Set(m.result.steps.flatMap((s) => s.tool_call_names))],
					success: m.result.success,
					error: m.result.error
				};
			}
			return base;
		})
	);

	function handleRun() {
		if (!prompt.trim() || running) return;

		const currentVersion = requestVersion;
		const userPrompt = prompt.trim();
		prompt = '';

		messages = [
			...messages,
			{ role: 'user', content: userPrompt, status: 'complete' },
			{ role: 'assistant', content: '', status: 'streaming', activeAgent: null }
		];

		running = true;
		completedAgents = [];
		activeAgents = new Set();
		flowStart = Math.floor(Date.now() / 1000);
		flowElapsed = 0;
		flowTimer = setInterval(() => {
			flowElapsed = Math.floor(Date.now() / 1000) - flowStart;
		}, 1000);

		const assistantIdx = messages.length - 1;

		controller = streamFlowRun(
			flowId,
			{ prompt: userPrompt, message_history: messageHistory },
			{
				onAgentStart(name) {
					if (requestVersion !== currentVersion) return;
					activeAgents = new Set([...activeAgents, name]);
					messages[assistantIdx] = {
						...messages[assistantIdx],
						activeAgent: name
					};
				},
				onAgentComplete(step: AgentStepResponse) {
					activeAgents = new Set([...activeAgents].filter((n) => n !== step.agent_name));
					completedAgents = [...completedAgents, step.agent_name];
				},
				onResult(r: FlowRunResponse) {
					if (requestVersion !== currentVersion) return;
					if (flowTimer) { clearInterval(flowTimer); flowTimer = null; }
					activeAgents = new Set();
					messages[assistantIdx] = {
						...messages[assistantIdx],
						content: r.output,
						status: 'complete',
						activeAgent: null,
						result: r
					};
					if (r.success && r.message_history) {
						messageHistory = r.message_history;
					}
					running = false;
					controller = null;
					onRunCompleted?.();
				},
				onError(error: string) {
					if (requestVersion !== currentVersion) return;
					if (flowTimer) { clearInterval(flowTimer); flowTimer = null; }
					activeAgents = new Set();
					messages[assistantIdx] = {
						...messages[assistantIdx],
						status: 'error',
						activeAgent: null,
						error
					};
					running = false;
					controller = null;
				}
			}
		);
	}

	function handleStop() {
		controller?.abort();
		controller = null;
		running = false;
		if (flowTimer) { clearInterval(flowTimer); flowTimer = null; }
		activeAgents = new Set();

		const lastIdx = messages.length - 1;
		if (lastIdx >= 0 && messages[lastIdx].role === 'assistant' && messages[lastIdx].status === 'streaming') {
			messages[lastIdx] = { ...messages[lastIdx], status: 'interrupted', activeAgent: null };
		}
	}

	function handleNewConversation() {
		controller?.abort();
		controller = null;
		running = false;
		if (flowTimer) { clearInterval(flowTimer); flowTimer = null; }
		requestVersion++;
		messages = [];
		messageHistory = null;
		prompt = '';
		completedAgents = [];
		activeAgents = new Set();
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter' && (e.metaKey || e.ctrlKey) && !running) {
			e.preventDefault();
			handleRun();
		}
	}

	const isMac = typeof navigator !== 'undefined' && navigator.platform?.includes('Mac');
	const hasMessages = $derived(messages.length > 0);
</script>

<div class="flex flex-1 flex-col gap-3">
	<!-- Thread -->
	<ConversationThread
		messages={threadMessages}
		emptyText="Send a prompt to run it through the flow"
		assistantLabel="Flow"
	>
		{#snippet messageHeader({ msg })}
			{#if msg.role === 'assistant' && msg.status === 'streaming' && (activeAgents.size > 0 || completedAgents.length > 0)}
				<PipelineStepper
					agents={detail.agents.map((a) => a.name)}
					{completedAgents}
					{activeAgents}
					elapsed={flowElapsed}
				/>
			{:else}
				<div class="flex items-center gap-2">
					<SeedAvatar seed={msg.identityLabel ?? 'Flow'} spinning={msg.status === 'streaming'} />
					<span class="font-mono text-[11px] font-medium uppercase tracking-[0.1em] text-fg-faint">
						{msg.identityLabel ?? 'Flow'}
					</span>
				</div>
			{/if}
		{/snippet}
		{#snippet messageFooter({ msg, index })}
			{@const flowMsg = messages[index]}
			{#if flowMsg?.role === 'assistant' && flowMsg.result?.steps}
				<AgentTrace steps={flowMsg.result.steps} />
			{/if}
		{/snippet}
	</ConversationThread>

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
				disabled={running}
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
						class="flex h-7 w-7 items-center justify-center rounded-full border border-edge bg-surface-2 text-accent-primary transition-[border-color,background-color] duration-150 hover:border-accent-primary/40 hover:bg-accent-primary/5 disabled:pointer-events-none disabled:opacity-30"
						onclick={handleRun}
						disabled={!prompt.trim()}
						aria-label="Run"
					>
						<Play size={14} fill="currentColor" />
					</button>
				{/if}
			</div>
		</div>
	</div>
</div>
