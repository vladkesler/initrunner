<script lang="ts">
	import type { TeamSummary } from '$lib/api/types';
	import TeamCard from './TeamCard.svelte';

	let { teams }: { teams: TeamSummary[] } = $props();
</script>

<div class="grid grid-cols-1 gap-2 md:grid-cols-2 lg:grid-cols-3">
	{#each teams as team, idx (team.id)}
		<TeamCard {team} {idx} />
	{/each}
</div>
