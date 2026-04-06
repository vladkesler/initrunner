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

export interface CostData {
	input_cost_usd: number;
	output_cost_usd: number;
	total_cost_usd: number;
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
	cost?: CostData | null;
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
	avatarSeeds?: string[];
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
	cost_usd: number | null;
}

export interface Provider {
	provider: string;
	model: string;
}

export interface HealthStatus {
	status: string;
	version: string;
}

export interface ToolEventData {
	agent_name?: string;
	tool_name: string;
	status: 'running' | 'ok' | 'error';
	phase: 'start' | 'complete';
	error_summary: string | null;
	duration_ms: number;
}

export interface UsageData {
	budget: { max_tokens: number | null; total_limit: number | null };
	model: string | null;
	provider: string | null;
}

export type SSEEvent =
	| { type: 'token'; data: string }
	| { type: 'tool_event'; data: ToolEventData }
	| { type: 'usage'; data: UsageData }
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

// -- Flow ---------------------------------------------------------------------

export interface FlowSummary {
	id: string;
	name: string;
	description: string;
	agent_count: number;
	agent_names: string[];
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

export interface FlowAgentDetail {
	name: string;
	role_path: string;
	agent_id: string | null;
	agent_name: string | null;
	sink: SinkDetail | null;
	needs: string[];
	trigger_summary: string | null;
	restart: RestartDetail;
	health_check: HealthCheckDetail;
	environment_count: number;
}

export interface FlowDetail {
	id: string;
	name: string;
	description: string;
	path: string;
	agents: FlowAgentDetail[];
	shared_memory_enabled: boolean;
	shared_documents_enabled: boolean;
}

export interface DelegateEvent {
	timestamp: string;
	source_agent: string;
	target_agent: string;
	status: string;
	source_run_id: string;
	flow_name: string | null;
	reason: string | null;
	trace: string | null;
	payload_preview: string;
}

export interface AgentStepResponse {
	agent_name: string;
	output: string;
	tokens_in: number;
	tokens_out: number;
	duration_ms: number;
	tool_calls: number;
	tool_call_names: string[];
	success: boolean;
	error: string | null;
}

export interface FlowRunResponse {
	output: string;
	output_mode: 'single' | 'multiple' | 'none';
	final_agent_name: string | null;
	steps: AgentStepResponse[];
	tokens_in: number;
	tokens_out: number;
	total_tokens: number;
	duration_ms: number;
	success: boolean;
	error: string | null;
	message_history: string | null;
	cost?: CostData | null;
}

export interface FlowThreadMessage {
	role: 'user' | 'assistant';
	content: string;
	status: 'complete' | 'streaming' | 'interrupted' | 'error';
	activeAgent?: string | null;
	result?: FlowRunResponse | null;
	error?: string | null;
}

export interface FlowStats {
	total_events: number;
	by_status: Record<string, number>;
}

export interface PatternInfo {
	name: string;
	description: string;
	fixed_topology: boolean;
	slot_names: string[];
	min_agents: number;
	max_agents: number | null;
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

export interface FlowBuilderOptions {
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

export interface FlowSeedResponse {
	flow_yaml: string;
	role_yamls: Record<string, string>;
	issues: ValidationIssue[];
	ready: boolean;
}

export interface FlowValidateResponse {
	issues: ValidationIssue[];
	ready: boolean;
}

export interface FlowSaveResponse {
	path: string;
	valid: boolean;
	issues: string[];
	next_steps: string[];
	flow_id: string;
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
	debate: { max_rounds: number; synthesize: boolean } | null;
	features: string[];
}

export interface PersonaStepResponse {
	persona_name: string;
	step_kind: 'persona' | 'synthesis';
	round_num: number | null;
	max_rounds: number | null;
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
	cost?: CostData | null;
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
	| { type: 'tool_event'; data: ToolEventData }
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

// -- MCP Hub ------------------------------------------------------------------

export interface McpAgentRef {
	agent_name: string;
	agent_id: string;
	role_path: string;
	tool_filter: string[];
	tool_exclude: string[];
	tool_prefix: string | null;
	defer: boolean;
}

export interface McpServer {
	server_id: string;
	display_name: string;
	transport: 'stdio' | 'sse' | 'streamable-http';
	command: string | null;
	args: string[];
	url: string | null;
	agent_refs: McpAgentRef[];
	health_status: 'healthy' | 'degraded' | 'unhealthy' | null;
	health_checked_at: string | null;
	cache_age_seconds: number | null;
}

export interface McpTool {
	name: string;
	description: string;
	input_schema: Record<string, unknown>;
}

export interface McpHealthResult {
	server_id: string;
	status: 'healthy' | 'degraded' | 'unhealthy';
	latency_ms: number;
	tool_count: number;
	error: string | null;
	checked_at: string;
}

export interface McpPlaygroundResult {
	tool_name: string;
	output: string;
	duration_ms: number;
	success: boolean;
	error: string | null;
}

export interface McpRegistryEntry {
	name: string;
	display_name: string;
	description: string;
	category: string;
	transport: string;
	command: string | null;
	args: string[];
	url: string | null;
	install_hint: string;
	homepage: string;
	tags: string[];
}

export interface McpHealthSummary {
	total: number;
	healthy: number;
	unhealthy: number;
}

// -- Timeline -----------------------------------------------------------------

export interface TimelineCost {
	total_cost_usd: number;
}

export interface TimelineEntry {
	run_id: string;
	start_time: string;
	end_time: string;
	duration_ms: number;
	status: 'success' | 'error';
	trigger_type: string | null;
	trigger_metadata: Record<string, unknown> | null;
	tokens_in: number;
	tokens_out: number;
	total_tokens: number;
	tool_calls: number;
	cost: TimelineCost | null;
}

export interface TimelineStats {
	total_runs: number;
	success_count: number;
	error_count: number;
	success_rate: number;
	total_tokens: number;
	avg_duration_ms: number;
	max_duration_ms: number;
	total_cost_usd: number | null;
}

export interface TimelineResponse {
	entries: TimelineEntry[];
	stats: TimelineStats;
}

// -- Cost Analytics -----------------------------------------------------------

export interface CostSummary {
	today: number | null;
	this_week: number | null;
	this_month: number | null;
	all_time: number | null;
	top_agents: AgentCost[];
	daily_trend: DailyCost[];
}

export interface AgentCost {
	agent_name: string;
	run_count: number;
	tokens_in: number;
	tokens_out: number;
	total_cost_usd: number | null;
	avg_cost_per_run: number | null;
}

export interface DailyCost {
	date: string;
	run_count: number;
	total_cost_usd: number | null;
}

export interface ModelCost {
	model: string;
	provider: string;
	run_count: number;
	tokens_in: number;
	tokens_out: number;
	total_cost_usd: number | null;
}
