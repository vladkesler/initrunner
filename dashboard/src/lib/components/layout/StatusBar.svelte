<script lang="ts">
	let { agentCount = 0 }: { agentCount?: number } = $props();
</script>

<footer class="flex h-8 items-center gap-4 border-t border-border bg-card px-3 font-mono text-[13px] text-muted-foreground">
	<span>
		<span class="text-dendrite">{agentCount}</span> agent{agentCount !== 1 ? 's' : ''}
	</span>
	<span class="ml-auto text-dendrite">InitRunner Dashboard</span>
</footer>
