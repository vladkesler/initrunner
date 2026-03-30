<script lang="ts">
	import { streamComposeRun } from '$lib/api/compose';
	import type {
		ComposeRunResponse,
		ComposeThreadMessage,
		ComposeDetail,
		ServiceStepResponse,
		ThreadMessage
	} from '$lib/api/types';
	import ConversationThread from '$lib/components/runs/ConversationThread.svelte';
	import ServiceTrace from './ServiceTrace.svelte';
	import PipelineStepper from './PipelineStepper.svelte';
	import SeedAvatar from '$lib/components/ui/SeedAvatar.svelte';
	import { Play, Square, RotateCcw } from 'lucide-svelte';

	let {
		composeId,
		detail,
		onRunCompleted
	}: {
		composeId: string;
		detail: ComposeDetail;
		onRunCompleted?: () => void;
	} = $props();

	let prompt = $state('');
	let messages: ComposeThreadMessage[] = $state([]);
	let messageHistory: string | null = $state(null);
	let running = $state(false);
	let controller: AbortController | null = $state(null);
	let requestVersion = $state(0);

	// Pipeline progress tracking
	let completedServices = $state<string[]>([]);
	let activeServices = $state(new Set<string>());
	let composeStart = $state(0);
	let composeElapsed = $state(0);
	let composeTimer: ReturnType<typeof setInterval> | null = null;

	const totalServices = $derived(detail.services.length);

	/** Adapt ComposeThreadMessage[] to ThreadMessage[] for ConversationThread. */
	const threadMessages = $derived<ThreadMessage[]>(
		messages.map((m) => {
			const base: ThreadMessage = {
				role: m.role,
				content: m.content,
				status: m.status,
				error: m.error,
				identityLabel: m.role === 'user' ? 'You' : (m.activeService ?? 'Compose')
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
			{ role: 'assistant', content: '', status: 'streaming', activeService: null }
		];

		running = true;
		completedServices = [];
		activeServices = new Set();
		composeStart = Math.floor(Date.now() / 1000);
		composeElapsed = 0;
		composeTimer = setInterval(() => {
			composeElapsed = Math.floor(Date.now() / 1000) - composeStart;
		}, 1000);

		const assistantIdx = messages.length - 1;

		controller = streamComposeRun(
			composeId,
			{ prompt: userPrompt, message_history: messageHistory },
			{
				onServiceStart(name) {
					if (requestVersion !== currentVersion) return;
					activeServices = new Set([...activeServices, name]);
					messages[assistantIdx] = {
						...messages[assistantIdx],
						activeService: name
					};
				},
				onServiceComplete(step: ServiceStepResponse) {
					activeServices = new Set([...activeServices].filter((n) => n !== step.service_name));
					completedServices = [...completedServices, step.service_name];
				},
				onResult(r: ComposeRunResponse) {
					if (requestVersion !== currentVersion) return;
					if (composeTimer) { clearInterval(composeTimer); composeTimer = null; }
					activeServices = new Set();
					messages[assistantIdx] = {
						...messages[assistantIdx],
						content: r.output,
						status: 'complete',
						activeService: null,
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
					if (composeTimer) { clearInterval(composeTimer); composeTimer = null; }
					activeServices = new Set();
					messages[assistantIdx] = {
						...messages[assistantIdx],
						status: 'error',
						activeService: null,
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
		if (composeTimer) { clearInterval(composeTimer); composeTimer = null; }
		activeServices = new Set();

		const lastIdx = messages.length - 1;
		if (lastIdx >= 0 && messages[lastIdx].role === 'assistant' && messages[lastIdx].status === 'streaming') {
			messages[lastIdx] = { ...messages[lastIdx], status: 'interrupted', activeService: null };
		}
	}

	function handleNewConversation() {
		controller?.abort();
		controller = null;
		running = false;
		if (composeTimer) { clearInterval(composeTimer); composeTimer = null; }
		requestVersion++;
		messages = [];
		messageHistory = null;
		prompt = '';
		completedServices = [];
		activeServices = new Set();
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
		emptyText="Send a prompt to run it through the composition"
		assistantLabel="Compose"
	>
		{#snippet messageHeader({ msg })}
			{#if msg.role === 'assistant' && msg.status === 'streaming' && (activeServices.size > 0 || completedServices.length > 0)}
				<PipelineStepper
					services={detail.services.map((s) => s.name)}
					{completedServices}
					{activeServices}
					elapsed={composeElapsed}
				/>
			{:else}
				<div class="flex items-center gap-2">
					<SeedAvatar seed={msg.identityLabel ?? 'Compose'} spinning={msg.status === 'streaming'} />
					<span class="font-mono text-[11px] font-medium uppercase tracking-[0.1em] text-fg-faint">
						{msg.identityLabel ?? 'Compose'}
					</span>
				</div>
			{/if}
		{/snippet}
		{#snippet messageFooter({ msg, index })}
			{@const composeMsg = messages[index]}
			{#if composeMsg?.role === 'assistant' && composeMsg.result?.steps}
				<ServiceTrace steps={composeMsg.result.steps} />
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
