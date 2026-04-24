<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import { X } from 'lucide-svelte';

	let open = $state(false);

	onMount(() => {
		function onKey(e: KeyboardEvent): void {
			const target = e.target as HTMLElement | null;
			if (target && ['INPUT', 'TEXTAREA'].includes(target.tagName)) return;
			if (e.key === '?' && !e.metaKey && !e.ctrlKey && !e.altKey) {
				open = !open;
				e.preventDefault();
			} else if (open && e.key === 'Escape') {
				open = false;
				e.preventDefault();
			}
		}
		window.addEventListener('keydown', onKey);
		return () => window.removeEventListener('keydown', onKey);
	});

	const onApprovals = $derived(page.url.pathname.startsWith('/approvals'));

	interface Row {
		k: string;
		label: string;
	}
	const global: Row[] = [
		{ k: '?', label: 'Toggle this overlay' },
		{ k: 'Esc', label: 'Close dialogs and drawers' }
	];
	const queue: Row[] = [
		{ k: 'j / k', label: 'Move focus down / up' },
		{ k: 'x', label: 'Toggle selection (single-call runs)' },
		{ k: 'A / D', label: 'Approve / deny focused row' },
		{ k: '↵', label: 'Open detail drawer' },
		{ k: '⇧ A / ⇧ D', label: 'Bulk approve / deny selected' }
	];
	const card: Row[] = [
		{ k: 'j / k', label: 'Move focus between cards' },
		{ k: 'A / D', label: 'Set decision on focused card' },
		{ k: '⇧ A / ⇧ D', label: 'Approve / deny every card' },
		{ k: '↵', label: 'Submit when every card has a decision' }
	];
</script>

{#if open}
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<!-- svelte-ignore a11y_click_events_have_key_events -->
	<div
		class="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
		onclick={() => (open = false)}
	>
		<!-- svelte-ignore a11y_no_static_element_interactions -->
		<!-- svelte-ignore a11y_click_events_have_key_events -->
		<section
			class="w-full max-w-2xl rounded-lg border border-edge bg-surface-0 shadow-2xl"
			onclick={(e) => e.stopPropagation()}
			role="dialog"
			aria-labelledby="shortcut-title"
		>
			<header class="flex items-center justify-between border-b border-edge-subtle px-4 py-3">
				<h2 id="shortcut-title" class="text-[15px] font-medium text-fg">Keyboard shortcuts</h2>
				<button
					type="button"
					class="rounded p-1 text-fg-faint hover:bg-surface-2 hover:text-fg-muted"
					aria-label="Close"
					onclick={() => (open = false)}
				>
					<X size={16} />
				</button>
			</header>

			<div class="grid grid-cols-2 gap-x-8 gap-y-6 px-4 py-4 text-[13px]">
				<div>
					<h3 class="mb-2 text-[10px] uppercase tracking-[0.15em] text-fg-faint">Global</h3>
					<dl class="flex flex-col gap-1">
						{#each global as row (row.k)}
							<div class="flex items-center justify-between gap-3">
								<kbd class="kbd">{row.k}</kbd>
								<span class="text-right text-fg-muted">{row.label}</span>
							</div>
						{/each}
					</dl>
				</div>

				{#if onApprovals}
					<div>
						<h3 class="mb-2 text-[10px] uppercase tracking-[0.15em] text-fg-faint">
							Approvals queue
						</h3>
						<dl class="flex flex-col gap-1">
							{#each queue as row (row.k)}
								<div class="flex items-center justify-between gap-3">
									<kbd class="kbd">{row.k}</kbd>
									<span class="text-right text-fg-muted">{row.label}</span>
								</div>
							{/each}
						</dl>
					</div>
					<div class="col-span-2">
						<h3 class="mb-2 text-[10px] uppercase tracking-[0.15em] text-fg-faint">
							Approval card
						</h3>
						<dl class="flex flex-col gap-1">
							{#each card as row (row.k)}
								<div class="flex items-center justify-between gap-3">
									<kbd class="kbd">{row.k}</kbd>
									<span class="text-right text-fg-muted">{row.label}</span>
								</div>
							{/each}
						</dl>
					</div>
				{/if}
			</div>

			<footer class="border-t border-edge-subtle px-4 py-2 text-[11px] text-fg-faint">
				Press <kbd class="kbd">?</kbd> anywhere to toggle this overlay.
			</footer>
		</section>
	</div>
{/if}

<style>
	.kbd {
		font-family: 'IBM Plex Mono', monospace;
		background: var(--color-surface-2, #28282e);
		padding: 1px 6px;
		border-radius: 3px;
		font-size: 10px;
		color: var(--color-fg-muted);
		white-space: nowrap;
	}
</style>
