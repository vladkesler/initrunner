import { request } from './client';
import type {
	McpServer,
	McpTool,
	McpHealthResult,
	McpPlaygroundResult,
	McpRegistryEntry,
	McpHealthSummary
} from './types';

export function listMcpServers(): Promise<McpServer[]> {
	return request('/api/mcp/servers');
}

export function getMcpServerTools(serverId: string): Promise<McpTool[]> {
	return request(`/api/mcp/servers/${serverId}/tools`);
}

export function checkMcpServerHealth(serverId: string): Promise<McpHealthResult> {
	return request(`/api/mcp/servers/${serverId}/health`, { method: 'POST' });
}

export function callMcpTool(body: {
	server_id: string;
	tool_name: string;
	arguments: Record<string, unknown>;
}): Promise<McpPlaygroundResult> {
	return request('/api/mcp/playground/call', {
		method: 'POST',
		body: JSON.stringify(body)
	});
}

export function getMcpRegistry(): Promise<McpRegistryEntry[]> {
	return request('/api/mcp/registry');
}

export function getMcpHealthSummary(): Promise<McpHealthSummary> {
	return request('/api/mcp/health-summary');
}

export function invalidateMcpCache(serverId: string): Promise<{ invalidated: boolean }> {
	return request(`/api/mcp/servers/${serverId}/cache`, { method: 'DELETE' });
}
