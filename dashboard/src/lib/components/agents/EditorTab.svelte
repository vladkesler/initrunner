<script lang="ts">
	import { validateYaml, saveAgent } from '$lib/api/builder';
	import YamlEditor from '$lib/components/ui/YamlEditor.svelte';

	let {
		agentId,
		yaml,
		path,
		agentName,
		onSaved
	}: {
		agentId: string;
		yaml: string;
		path: string;
		agentName: string;
		onSaved?: () => void;
	} = $props();

	const directory = $derived(path.substring(0, path.lastIndexOf('/')));
	const filename = $derived(path.substring(path.lastIndexOf('/') + 1));

	async function validate(text: string) {
		return validateYaml(text);
	}

	async function save(text: string) {
		await saveAgent({
			yaml_text: text,
			directory,
			filename,
			force: true
		});
	}
</script>

<YamlEditor
	{yaml}
	{path}
	entityName={agentName}
	nameChangeWarning="Changing the agent name will disconnect run history and memory from the previous name."
	{validate}
	{save}
	{onSaved}
/>
