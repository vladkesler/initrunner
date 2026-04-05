<script lang="ts">
	import RunPanel from './RunPanel.svelte';
	import { X } from 'lucide-svelte';

	let {
		agentId,
		agentName,
		onClose
	}: {
		agentId: string;
		agentName: string;
		onClose: () => void;
	} = $props();

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Escape') onClose();
	}
</script>

<svelte:window onkeydown={handleKeydown} />

<!-- Backdrop -->
<!-- svelte-ignore a11y_no_static_element_interactions -->
<div class="fixed inset-0 z-40 bg-black/40" onclick={onClose} onkeydown={(e) => e.key === 'Escape' && onClose()}></div>

<!-- Drawer panel -->
<div class="fixed inset-y-0 right-0 z-50 flex w-full max-w-md flex-col border-l border-edge bg-surface-0 shadow-2xl">
	<!-- Header -->
	<div class="flex items-center justify-between border-b border-edge px-5 py-4">
		<h2 class="truncate text-[14px] font-semibold text-fg">{agentName}</h2>
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
		<RunPanel {agentId} {agentName} />
	</div>
</div>
