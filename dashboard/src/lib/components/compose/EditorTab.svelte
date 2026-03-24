<script lang="ts">
	import { validateCompose, saveComposeYaml } from '$lib/api/compose';
	import YamlEditor from '$lib/components/ui/YamlEditor.svelte';

	let {
		composeId,
		yaml,
		path,
		composeName,
		onSaved
	}: {
		composeId: string;
		yaml: string;
		path: string;
		composeName: string;
		onSaved?: () => void;
	} = $props();

	async function validate(text: string) {
		return validateCompose(text);
	}

	async function save(text: string) {
		await saveComposeYaml(composeId, text);
	}
</script>

<YamlEditor
	{yaml}
	{path}
	entityName={composeName}
	nameChangeWarning="Changing the compose name will split event history. Existing events will remain under the previous name."
	{validate}
	{save}
	{onSaved}
/>
