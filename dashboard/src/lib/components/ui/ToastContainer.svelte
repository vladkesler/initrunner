<script lang="ts">
	import { fly } from 'svelte/transition';
	import { getToasts, dismissToast, type ToastLevel } from '$lib/stores/toast.svelte';
	import { XCircle, CheckCircle, AlertTriangle, Info, X } from 'lucide-svelte';

	const toasts = $derived(getToasts());

	const icons: Record<ToastLevel, typeof XCircle> = {
		error: XCircle,
		success: CheckCircle,
		warn: AlertTriangle,
		info: Info
	};

	const borderColors: Record<ToastLevel, string> = {
		error: 'border-l-fail',
		success: 'border-l-ok',
		warn: 'border-l-warn',
		info: 'border-l-info'
	};

	const iconColors: Record<ToastLevel, string> = {
		error: 'text-fail',
		success: 'text-ok',
		warn: 'text-warn',
		info: 'text-info'
	};
</script>

<div
	class="fixed bottom-6 right-6 z-50 flex flex-col-reverse gap-2"
	role="status"
	aria-live="polite"
>
	{#each toasts as t (t.id)}
		{@const Icon = icons[t.level]}
		<div
			class="flex w-80 items-start gap-3 border border-edge bg-surface-1 px-4 py-3 shadow-lg {borderColors[t.level]} border-l-2"
			transition:fly={{ x: 100, duration: 200 }}
		>
			<Icon size={16} class="mt-0.5 shrink-0 {iconColors[t.level]}" />
			<p class="min-w-0 flex-1 text-[13px] text-fg-muted">{t.message}</p>
			<button
				class="shrink-0 text-fg-faint transition-[color] duration-150 hover:text-fg-muted"
				onclick={() => dismissToast(t.id)}
				aria-label="Dismiss"
			>
				<X size={14} />
			</button>
		</div>
	{/each}
</div>
