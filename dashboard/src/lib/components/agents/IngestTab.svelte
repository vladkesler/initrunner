<script lang="ts">
	import { onMount } from 'svelte';
	import {
		getIngestDocuments,
		getIngestSummary,
		deleteIngestDocument,
		addIngestUrl,
		uploadIngestFiles,
		streamIngest
	} from '$lib/api/agents';
	import type { IngestDocument, IngestSummary } from '$lib/api/types';
	import { Skeleton } from '$lib/components/ui/skeleton';
	import {
		RefreshCw,
		Database,
		Layers,
		Clock,
		FileText,
		Globe,
		Trash2,
		Upload,
		Link
	} from 'lucide-svelte';
	import { toast } from '$lib/stores/toast.svelte';

	let { agentId, hasIngest }: { agentId: string; hasIngest: boolean } = $props();

	let documents = $state<IngestDocument[]>([]);
	let summary = $state<IngestSummary | null>(null);
	let loading = $state(true);
	let ingesting = $state(false);
	let ingestProgress = $state<{ path: string; status: string }[]>([]);
	let showUrlInput = $state(false);
	let urlValue = $state('');
	let uploading = $state(false);
	let addingUrl = $state(false);
	let confirmDeleteSource = $state<string | null>(null);
	let confirmTimer: ReturnType<typeof setTimeout> | null = null;
	let fileInputRef = $state<HTMLInputElement>(undefined!);
	let ingestController: AbortController | null = null;

	async function loadData() {
		loading = true;
		try {
			const [docs, sum] = await Promise.all([
				getIngestDocuments(agentId),
				getIngestSummary(agentId)
			]);
			documents = docs;
			summary = sum;
		} catch {
			toast.error('Failed to load documents');
		} finally {
			loading = false;
		}
	}

	function handleIngest(force: boolean) {
		ingesting = true;
		ingestProgress = [];
		ingestController = streamIngest(agentId, force, {
			onProgress(path, status) {
				ingestProgress = [...ingestProgress, { path, status }];
			},
			onResult() {
				ingesting = false;
				ingestController = null;
				loadData();
			},
			onError() {
				ingesting = false;
				ingestController = null;
				toast.error('Ingestion failed');
				loadData();
			}
		});
	}

	async function handleUpload(event: Event) {
		const input = event.target as HTMLInputElement;
		if (!input.files?.length) return;
		uploading = true;
		try {
			await uploadIngestFiles(agentId, input.files);
			await loadData();
		} catch {
			toast.error('File upload failed');
		} finally {
			uploading = false;
			input.value = '';
		}
	}

	async function handleAddUrl() {
		const url = urlValue.trim();
		if (!url) return;
		addingUrl = true;
		try {
			await addIngestUrl(agentId, url);
			urlValue = '';
			showUrlInput = false;
			await loadData();
		} catch {
			toast.error('Failed to add URL');
		} finally {
			addingUrl = false;
		}
	}

	function handleDelete(source: string) {
		if (confirmDeleteSource === source) {
			// Confirmed
			if (confirmTimer) clearTimeout(confirmTimer);
			confirmDeleteSource = null;
			documents = documents.filter((d) => d.source !== source);
			deleteIngestDocument(agentId, source).catch(() => { toast.error('Failed to delete document'); loadData(); });
		} else {
			// First click
			if (confirmTimer) clearTimeout(confirmTimer);
			confirmDeleteSource = source;
			confirmTimer = setTimeout(() => {
				confirmDeleteSource = null;
			}, 3000);
		}
	}

	function formatDate(ts: string): string {
		try {
			const d = new Date(ts);
			return (
				d.toLocaleDateString([], { month: 'short', day: 'numeric' }) +
				' ' +
				d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
			);
		} catch {
			return ts;
		}
	}

	function statusClasses(status: string): string {
		switch (status) {
			case 'new':
				return 'bg-ok/10 text-ok';
			case 'updated':
				return 'bg-info/10 text-info';
			case 'error':
				return 'bg-fail/10 text-fail';
			default:
				return 'bg-surface-2 text-fg-faint';
		}
	}

	function sourceName(source: string): string {
		if (source.startsWith('http://') || source.startsWith('https://')) return source;
		const parts = source.split('/');
		return parts[parts.length - 1] || source;
	}

	onMount(() => {
		if (hasIngest) loadData();
	});
</script>

{#if !hasIngest}
	<div class="flex flex-col items-center justify-center py-16 text-center">
		<p class="text-[13px] text-fg-faint">This agent has no ingestion configuration.</p>
		<p class="mt-1 text-[12px] text-fg-faint">
			Add an ingest block to the role YAML to enable document management.
		</p>
	</div>
{:else}
	<div class="space-y-4">
		<!-- Summary strip -->
		{#if loading}
			<div class="grid grid-cols-3 gap-2">
				{#each Array(3) as _}
					<Skeleton class="h-[60px] bg-surface-1" />
				{/each}
			</div>
		{:else if summary}
			<div class="grid grid-cols-3 gap-2">
				<div
					class="card-surface flex items-center gap-2.5 bg-surface-1 px-3 py-2 animate-fade-in-up"
					style="animation-delay: 0ms"
				>
					<Database size={14} class="shrink-0 text-accent-primary/60" />
					<div>
						<div
							class="font-mono text-[18px] font-semibold tracking-[-0.02em] text-fg"
							style="font-variant-numeric: tabular-nums"
						>
							{summary.total_documents.toLocaleString()}
						</div>
						<div class="text-[12px] text-fg-faint">documents</div>
					</div>
				</div>
				<div
					class="card-surface flex items-center gap-2.5 bg-surface-1 px-3 py-2 animate-fade-in-up"
					style="animation-delay: 60ms"
				>
					<Layers size={14} class="shrink-0 text-accent-primary/60" />
					<div>
						<div
							class="font-mono text-[18px] font-semibold tracking-[-0.02em] text-fg"
							style="font-variant-numeric: tabular-nums"
						>
							{summary.total_chunks.toLocaleString()}
						</div>
						<div class="text-[12px] text-fg-faint">chunks</div>
					</div>
				</div>
				<div
					class="card-surface flex items-center gap-2.5 bg-surface-1 px-3 py-2 animate-fade-in-up"
					style="animation-delay: 120ms"
				>
					<Clock size={14} class="shrink-0 text-accent-primary/60" />
					<div>
						<div class="font-mono text-[13px] font-medium text-fg">
							{summary.last_ingested_at ? formatDate(summary.last_ingested_at) : 'Never'}
						</div>
						<div class="text-[12px] text-fg-faint">last ingested</div>
					</div>
				</div>
			</div>
		{/if}

		<!-- Action bar -->
		<div class="flex flex-wrap items-center gap-2">
			<button
				class="inline-flex items-center gap-1.5 rounded-full border border-edge px-3 py-1.5 text-[13px] text-fg-faint transition-[color,background-color,border-color] duration-150 hover:border-accent-primary/20 hover:bg-surface-2 hover:text-fg-muted disabled:opacity-40"
				onclick={() => handleIngest(false)}
				disabled={ingesting || uploading}
			>
				<RefreshCw size={12} />
				Re-ingest
			</button>
			<button
				class="inline-flex items-center gap-1.5 rounded-full border border-edge px-3 py-1.5 text-[13px] text-fg-faint transition-[color,background-color,border-color] duration-150 hover:border-accent-primary/20 hover:bg-surface-2 hover:text-fg-muted disabled:opacity-40"
				onclick={() => handleIngest(true)}
				disabled={ingesting || uploading}
			>
				<RefreshCw size={12} />
				Force Re-ingest
			</button>
			<button
				class="inline-flex items-center gap-1.5 rounded-full border border-edge px-3 py-1.5 text-[13px] text-fg-faint transition-[color,background-color,border-color] duration-150 hover:border-accent-primary/20 hover:bg-surface-2 hover:text-fg-muted disabled:opacity-40"
				onclick={() => (showUrlInput = !showUrlInput)}
				disabled={ingesting || uploading}
			>
				<Link size={12} />
				Add URL
			</button>
			<button
				class="inline-flex items-center gap-1.5 rounded-full border border-edge px-3 py-1.5 text-[13px] text-fg-faint transition-[color,background-color,border-color] duration-150 hover:border-accent-primary/20 hover:bg-surface-2 hover:text-fg-muted disabled:opacity-40"
				onclick={() => fileInputRef.click()}
				disabled={ingesting || uploading}
			>
				<Upload size={12} />
				{uploading ? 'Uploading...' : 'Upload Files'}
			</button>
			<input
				bind:this={fileInputRef}
				type="file"
				multiple
				class="hidden"
				onchange={handleUpload}
			/>
			<button
				class="ml-auto inline-flex items-center gap-1.5 rounded-full border border-edge px-3 py-1.5 text-[13px] text-fg-faint transition-[color,background-color,border-color] duration-150 hover:border-accent-primary/20 hover:bg-surface-2 hover:text-fg-muted"
				onclick={loadData}
				aria-label="Refresh"
			>
				<RefreshCw size={12} />
			</button>
		</div>

		<!-- URL input -->
		{#if showUrlInput}
			<div class="flex items-center gap-2">
				<input
					type="url"
					bind:value={urlValue}
					placeholder="e.g., https://docs.example.com/api-reference"
					class="flex-1 border border-edge bg-surface-1 px-3 py-1.5 font-mono text-[13px] text-fg placeholder:text-fg-faint focus:border-accent-primary/40 focus:shadow-[0_0_0_3px_oklch(0.91_0.20_128/0.08)] focus:outline-none"
					onkeydown={(e) => e.key === 'Enter' && handleAddUrl()}
					disabled={addingUrl}
				/>
				<button
					class="inline-flex items-center gap-1.5 rounded-full border border-edge px-3 py-1.5 text-[13px] text-fg-faint transition-[color,background-color,border-color] duration-150 hover:border-accent-primary/20 hover:bg-surface-2 hover:text-fg-muted disabled:opacity-40"
					onclick={handleAddUrl}
					disabled={addingUrl || !urlValue.trim()}
				>
					{addingUrl ? 'Adding...' : 'Add'}
				</button>
			</div>
		{/if}

		<!-- Progress panel -->
		{#if ingesting}
			<div class="card-surface bg-surface-1 p-3 active-border">
				<div
					class="max-h-48 space-y-1 overflow-y-auto font-mono text-[13px] scrollbar-none"
				>
					{#each ingestProgress as entry}
						<div class="flex items-center gap-2">
							<span class="flex-1 truncate text-fg-muted" title={entry.path}>
								{sourceName(entry.path)}
							</span>
							<span
								class="rounded-full px-2 py-0.5 text-[11px] {statusClasses(entry.status)}"
							>
								{entry.status}
							</span>
						</div>
					{/each}
					{#if ingestProgress.length === 0}
						<p class="text-fg-faint">Starting ingestion...</p>
					{/if}
				</div>
			</div>
		{/if}

		<!-- Document list -->
		{#if loading}
			<Skeleton class="h-48 bg-surface-1" />
		{:else if documents.length === 0}
			<div class="flex flex-col items-center justify-center py-16 text-center">
				<p class="text-[13px] text-fg-faint">No documents ingested yet</p>
				<p class="mt-1 text-[12px] text-fg-faint">
					Upload files or add URLs to populate the document store.
				</p>
			</div>
		{:else}
			<div class="space-y-2">
				{#each documents as doc (doc.source)}
					<div class="card-surface bg-surface-1 p-3">
						<div class="flex items-start gap-2.5">
							{#if doc.is_url}
								<Globe size={14} class="mt-0.5 shrink-0 text-accent-secondary/60" />
							{:else}
								<FileText size={14} class="mt-0.5 shrink-0 text-accent-primary/60" />
							{/if}
							<div class="min-w-0 flex-1">
								<p
									class="truncate font-mono text-[13px] text-fg-muted"
									title={doc.source}
								>
									{sourceName(doc.source)}
								</p>
								<div class="mt-1.5 flex flex-wrap items-center gap-2">
									<span
										class="rounded-[2px] bg-accent-primary/10 px-2 py-0.5 font-mono text-[11px] text-accent-primary"
									>
										{doc.chunk_count} chunks
									</span>
									{#if doc.is_managed}
										<span
											class="rounded-full bg-accent-secondary/10 px-2 py-0.5 font-mono text-[11px] text-accent-secondary"
										>
											managed
										</span>
									{:else}
										<span
											class="rounded-full bg-surface-2 px-2 py-0.5 font-mono text-[11px] text-fg-faint"
										>
											from config
										</span>
									{/if}
									<span class="ml-auto text-[11px] text-fg-faint">
										{formatDate(doc.ingested_at)}
									</span>
								</div>
							</div>
							{#if doc.is_managed}
								<button
									class="shrink-0 border border-edge p-1.5 text-fg-faint transition-[color,border-color] duration-150 hover:border-fail hover:text-fail"
									onclick={() => handleDelete(doc.source)}
									aria-label="Delete source"
								>
									{#if confirmDeleteSource === doc.source}
										<span class="px-1 text-[11px] text-fail">Confirm?</span>
									{:else}
										<Trash2 size={12} />
									{/if}
								</button>
							{/if}
						</div>
					</div>
				{/each}
			</div>
			<p class="text-[12px] text-fg-faint">{documents.length} documents</p>
		{/if}
	</div>
{/if}
