export interface AgentSummary {
	id: string;
	name: string;
	description: string;
	tags: string[];
	provider: string;
	model: string;
	features: string[];
	path: string;
	error: string | null;
}

// -- Agent Detail -------------------------------------------------------------

export interface ItemSummary {
	type: string;
	summary: string;
	config: Record<string, unknown>;
}

export interface AgentDetail {
	id: string;
	name: string;
	description: string;
	tags: string[];
	path: string;
	error: string | null;
	author: string;
	team: string;
	version: string;
	model: Record<string, unknown>;
	output: Record<string, unknown>;
	guardrails: Record<string, unknown>;
	memory: Record<string, unknown> | null;
	ingest: Record<string, unknown> | null;
	reasoning: Record<string, unknown> | null;
	autonomy: Record<string, unknown> | null;
	tools: ItemSummary[];
	triggers: ItemSummary[];
	sinks: ItemSummary[];
	capabilities: ItemSummary[];
	skills: string[];
	skill_refs: SkillRef[];
	features: string[];
	tool_search: {
		enabled: boolean;
		always_available: string[];
		max_results: number;
		threshold: number;
	} | null;
	provider_warning: string | null;
}

export interface RunRequest {
	agent_id: string;
	prompt: string;
	model_override?: string | null;
	message_history?: string | null;
}

export interface RunResponse {
	run_id: string;
	output: string;
	tokens_in: number;
	tokens_out: number;
	total_tokens: number;
	tool_calls: number;
	tool_call_names: string[];
	duration_ms: number;
	success: boolean;
	error: string | null;
	message_history?: string | null;
}

/** Fields ConversationThread actually renders from a run result. */
export interface ThreadResultMeta {
	tokens_in: number;
	tokens_out: number;
	duration_ms: number;
	tool_calls: number;
	tool_call_names: string[];
	success: boolean;
	error: string | null;
}

export interface ThreadMessage {
	role: 'user' | 'assistant';
	content: string;
	status: 'complete' | 'streaming' | 'interrupted' | 'error';
	result?: ThreadResultMeta | null;
	error?: string | null;
	identityLabel?: string | null;
}

export interface AuditRecord {
	run_id: string;
	agent_name: string;
	timestamp: string;
	user_prompt: string;
	model: string;
	provider: string;
	output: string;
	tokens_in: number;
	tokens_out: number;
	total_tokens: number;
	tool_calls: number;
	duration_ms: number;
	success: boolean;
	error: string | null;
	trigger_type: string | null;
}

export interface Provider {
	provider: string;
	model: string;
}

export interface HealthStatus {
	status: string;
	version: string;
}

export type SSEEvent =
	| { type: 'token'; data: string }
	| { type: 'result'; data: RunResponse }
	| { type: 'error'; data: string };

// -- Trigger Stats ------------------------------------------------------------

export interface TriggerStat {
	trigger_type: string;
	summary: string;
	fire_count: number;
	success_count: number;
	fail_count: number;
	last_fire_time: string | null;
	avg_duration_ms: number;
	last_error: string | null;
	next_check_time: string | null;
}

// -- Audit Stats --------------------------------------------------------------

export interface TopAgent {
	name: string;
	count: number;
	avg_duration_ms: number;
}

export interface AuditStats {
	total_runs: number;
	success_rate: number;
	total_tokens: number;
	avg_duration_ms: number;
	top_agents: TopAgent[];
}

// -- System / Doctor ----------------------------------------------------------

export interface DoctorCheck {
	name: string;
	status: 'ok' | 'warn' | 'fail';
	message: string;
}

export interface DoctorResponse {
	checks: DoctorCheck[];
	embedding_checks: DoctorCheck[];
}

export interface ToolType {
	name: string;
	description: string;
}

// -- Compose ------------------------------------------------------------------

export interface ComposeSummary {
	id: string;
	name: string;
	description: string;
	service_count: number;
	service_names: string[];
	path: string;
	error: string | null;
}

export interface SinkDetail {
	summary: string;
	strategy: string;
	targets: string[];
	queue_size: number;
	timeout_seconds: number;
	circuit_breaker_threshold: number | null;
}

export interface RestartDetail {
	condition: string;
	max_retries: number;
	delay_seconds: number;
}

export interface HealthCheckDetail {
	interval_seconds: number;
	timeout_seconds: number;
	retries: number;
}

export interface ComposeServiceDetail {
	name: string;
	role_path: string;
	agent_id: string | null;
	agent_name: string | null;
	sink: SinkDetail | null;
	depends_on: string[];
	trigger_summary: string | null;
	restart: RestartDetail;
	health_check: HealthCheckDetail;
	environment_count: number;
}

export interface ComposeDetail {
	id: string;
	name: string;
	description: string;
	path: string;
	services: ComposeServiceDetail[];
	shared_memory_enabled: boolean;
	shared_documents_enabled: boolean;
}

export interface DelegateEvent {
	timestamp: string;
	source_service: string;
	target_service: string;
	status: string;
	source_run_id: string;
	compose_name: string | null;
	reason: string | null;
	trace: string | null;
	payload_preview: string;
}

export interface ServiceStepResponse {
	service_name: string;
	output: string;
	tokens_in: number;
	tokens_out: number;
	duration_ms: number;
	tool_calls: number;
	tool_call_names: string[];
	success: boolean;
	error: string | null;
}

export interface ComposeRunResponse {
	output: string;
	output_mode: 'single' | 'multiple' | 'none';
	final_service_name: string | null;
	steps: ServiceStepResponse[];
	tokens_in: number;
	tokens_out: number;
	total_tokens: number;
	duration_ms: number;
	success: boolean;
	error: string | null;
	message_history: string | null;
}

export interface ComposeThreadMessage {
	role: 'user' | 'assistant';
	content: string;
	status: 'complete' | 'streaming' | 'interrupted' | 'error';
	activeService?: string | null;
	result?: ComposeRunResponse | null;
	error?: string | null;
}

export interface ComposeStats {
	total_events: number;
	by_status: Record<string, number>;
}

export interface PatternInfo {
	name: string;
	description: string;
	fixed_topology: boolean;
	slot_names: string[];
	min_services: number;
	max_services: number | null;
}

export interface AgentSlotModel {
	provider: string;
	name: string;
	base_url: string | null;
	api_key_env: string | null;
}

export interface AgentSlotOption {
	id: string;
	name: string;
	description: string;
	path: string;
	tags: string[];
	features: string[];
	model: AgentSlotModel | null;
}

export interface SlotAssignment {
	slot: string;
	agent_id: string | null;
}

export interface ProviderModels {
	provider: string;
	models: { name: string; description: string }[];
}

export interface ProviderPreset {
	name: string;
	label: string;
	base_url: string;
	api_key_env: string;
	placeholder: string;
	key_configured: boolean;
}

export interface ComposeBuilderOptions {
	patterns: PatternInfo[];
	agents: AgentSlotOption[];
	providers: ProviderModels[];
	detected_provider: string | null;
	detected_model: string | null;
	save_dirs: string[];
	custom_presets: ProviderPreset[];
	ollama_models: string[];
	ollama_base_url: string;
}

export interface ValidationIssue {
	field: string;
	message: string;
	severity: string;
}

export interface ComposeSeedResponse {
	compose_yaml: string;
	role_yamls: Record<string, string>;
	issues: ValidationIssue[];
	ready: boolean;
}

export interface ComposeValidateResponse {
	issues: ValidationIssue[];
	ready: boolean;
}

export interface ComposeSaveResponse {
	path: string;
	valid: boolean;
	issues: string[];
	next_steps: string[];
	compose_id: string;
}

// -- Ingestion ----------------------------------------------------------------

export interface IngestDocument {
	source: string;
	chunk_count: number;
	ingested_at: string;
	content_hash: string;
	is_url: boolean;
	is_managed: boolean;
}

export interface IngestSummary {
	total_documents: number;
	total_chunks: number;
	store_path: string;
	sources_config: string[];
	managed_count: number;
	last_ingested_at: string | null;
}

export interface IngestFileResult {
	path: string;
	status: 'new' | 'updated' | 'skipped' | 'error';
	chunks: number;
	error: string | null;
}

export interface IngestStats {
	new: number;
	updated: number;
	skipped: number;
	errored: number;
	total_chunks: number;
	file_results: IngestFileResult[];
}

export type IngestSSEEvent =
	| { type: 'progress'; data: { path: string; status: string } }
	| { type: 'result'; data: IngestStats }
	| { type: 'error'; data: string };

// -- Agent Memory / Sessions --------------------------------------------------

export interface MemoryItem {
	id: number;
	content: string;
	category: string;
	memory_type: string;
	created_at: string;
	consolidated_at: string | null;
}

export interface SessionSummary {
	session_id: string;
	agent_name: string;
	timestamp: string;
	message_count: number;
	preview: string;
}

export interface SessionMessage {
	role: string;
	content: string;
}

export interface SessionDetail {
	session_id: string;
	messages: SessionMessage[];
}

// -- Team ---------------------------------------------------------------------

export interface PersonaDetail {
	name: string;
	role: string;
	model: Record<string, unknown> | null;
	tools: ItemSummary[];
	tools_mode: string;
	environment_count: number;
}

export interface TeamSummary {
	id: string;
	name: string;
	description: string;
	strategy: string;
	persona_count: number;
	persona_names: string[];
	provider: string;
	model: string;
	has_model_overrides: boolean;
	features: string[];
	path: string;
	error: string | null;
}

export interface TeamDetail {
	id: string;
	name: string;
	description: string;
	path: string;
	error: string | null;
	strategy: string;
	model: Record<string, unknown>;
	personas: PersonaDetail[];
	guardrails: Record<string, unknown>;
	handoff_max_chars: number;
	shared_memory: Record<string, unknown>;
	shared_documents: Record<string, unknown>;
	tools: ItemSummary[];
	observability: Record<string, unknown> | null;
	features: string[];
}

export interface PersonaStepResponse {
	persona_name: string;
	output: string;
	tokens_in: number;
	tokens_out: number;
	duration_ms: number;
	tool_calls: number;
	tool_call_names: string[];
	success: boolean;
	error: string | null;
}

export interface TeamRunResponse {
	team_run_id: string;
	output: string;
	steps: PersonaStepResponse[];
	tokens_in: number;
	tokens_out: number;
	total_tokens: number;
	duration_ms: number;
	success: boolean;
	error: string | null;
}

export interface TeamThreadMessage {
	role: 'user' | 'assistant';
	content: string;
	status: 'complete' | 'streaming' | 'interrupted' | 'error';
	activePersona?: string | null;
	result?: TeamRunResponse | null;
	error?: string | null;
}

export type TeamSSEEvent =
	| { type: 'persona_start'; data: string }
	| { type: 'persona_complete'; data: PersonaStepResponse }
	| { type: 'result'; data: TeamRunResponse }
	| { type: 'error'; data: string };

// -- Skills -------------------------------------------------------------------

export interface RequirementStatus {
	name: string;
	kind: 'env' | 'bin';
	met: boolean;
	detail: string;
}

export interface SkillToolSummary {
	type: string;
	summary: string;
}

export interface SkillSummary {
	id: string;
	name: string;
	description: string;
	scope: string;
	has_tools: boolean;
	tool_count: number;
	is_directory_form: boolean;
	requirements_met: boolean;
	requirement_count: number;
	path: string;
	error: string | null;
}

export interface SkillAgentRef {
	id: string;
	name: string;
}

export interface SkillDetail {
	id: string;
	name: string;
	description: string;
	scope: string;
	path: string;
	is_directory_form: boolean;
	has_resources: boolean;
	error: string | null;
	license: string;
	compatibility: string;
	metadata: Record<string, string>;
	tools: SkillToolSummary[];
	requirements: RequirementStatus[];
	requirements_met: boolean;
	prompt: string;
	prompt_preview: string;
	used_by_agents: SkillAgentRef[];
}

export interface SkillRef {
	name: string;
	skill_id: string | null;
}

// -- Team ---------------------------------------------------------------------

export interface TeamBuilderOptions {
	providers: ProviderModels[];
	agents: AgentSlotOption[];
	detected_provider: string | null;
	detected_model: string | null;
	save_dirs: string[];
	custom_presets: ProviderPreset[];
	ollama_models: string[];
	ollama_base_url: string;
}

export interface PersonaSeedModel {
	provider: string;
	name: string;
	base_url: string | null;
	api_key_env: string | null;
}

export interface PersonaSeedEntry {
	name: string;
	role: string;
	model: PersonaSeedModel | null;
}

export interface TeamSeedResponse {
	yaml_text: string;
	explanation: string;
	issues: ValidationIssue[];
	ready: boolean;
}

export interface TeamValidateResponse {
	issues: ValidationIssue[];
	ready: boolean;
}

export interface TeamSaveResponse {
	path: string;
	valid: boolean;
	issues: string[];
	next_steps: string[];
	team_id: string;
}
