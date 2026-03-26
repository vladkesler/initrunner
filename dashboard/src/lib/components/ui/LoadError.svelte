<script lang="ts">
	let { message, onRetry }: { message: string; onRetry?: () => void } = $props();
</script>

<div class="border border-fail/20 bg-fail/5 px-4 py-3">
	<p class="text-[13px] text-fail">{message}</p>
	{#if onRetry}
		<button
			class="mt-2 text-[13px] text-fg-faint underline transition-[color] duration-150 hover:text-fg-muted"
			onclick={onRetry}
		>
			Retry
		</button>
	{/if}
</div>
