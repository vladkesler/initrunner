<script lang="ts">
	import { Button } from '$lib/components/ui/button';
	import { AlertTriangle, Loader2 } from 'lucide-svelte';

	let {
		entityName,
		entityType,
		open = $bindable(false),
		onConfirm,
		onCancel
	}: {
		entityName: string;
		entityType: string;
		open: boolean;
		onConfirm: () => Promise<void>;
		onCancel: () => void;
	} = $props();

	let confirmation = $state('');
	let deleting = $state(false);
	let error = $state('');

	const canDelete = $derived(confirmation === entityName);

	async function handleDelete() {
		if (!canDelete) return;
		deleting = true;
		error = '';
		try {
			await onConfirm();
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			deleting = false;
		}
	}

	function handleCancel() {
		confirmation = '';
		error = '';
		onCancel();
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter' && canDelete && !deleting) {
			handleDelete();
		} else if (e.key === 'Escape') {
			handleCancel();
		}
	}
</script>

{#if open}
	<div class="card-surface border border-edge bg-surface-1 p-5 animate-fade-in-up" role="alertdialog" aria-labelledby="confirm-delete-title">
		<div class="flex items-start gap-3">
			<div class="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-fail/10">
				<AlertTriangle size={16} class="text-fail" />
			</div>
			<div class="flex-1 space-y-3">
				<h3 id="confirm-delete-title" class="text-[14px] font-medium text-fg">
					Delete {entityType}
				</h3>
				<p class="text-[13px] text-fg-muted">
					This will permanently delete <span class="font-mono font-medium text-fg">{entityName}</span>
					and its YAML file. This cannot be undone.
				</p>

				<div>
					<label for="confirm-delete-input" class="mb-1.5 block text-[12px] text-fg-faint">
						Type <span class="font-mono font-medium text-fg">{entityName}</span> to confirm
					</label>
					<!-- svelte-ignore a11y_autofocus -->
					<input
						id="confirm-delete-input"
						bind:value={confirmation}
						onkeydown={handleKeydown}
						autofocus
						autocomplete="off"
						spellcheck="false"
						class="w-full border border-edge bg-surface-0 px-2.5 py-1.5 font-mono text-[13px] text-fg outline-none transition-[border-color,box-shadow] duration-150 placeholder:text-fg-faint focus:border-accent-primary/40 focus:shadow-[0_0_0_3px_oklch(0.91_0.20_128/0.08)]"
					/>
				</div>

				{#if error}
					<p class="border-l-2 border-l-fail bg-fail/5 px-3 py-1.5 font-mono text-[12px] text-fail">{error}</p>
				{/if}

				<div class="flex items-center justify-end gap-2 pt-1">
					<Button variant="ghost" size="sm" onclick={handleCancel} disabled={deleting}>
						Cancel
					</Button>
					<Button
						variant="destructive"
						size="sm"
						onclick={handleDelete}
						disabled={!canDelete || deleting}
					>
						{#if deleting}
							<Loader2 size={13} class="animate-spin" />
						{/if}
						Delete {entityType}
					</Button>
				</div>
			</div>
		</div>
	</div>
{/if}
