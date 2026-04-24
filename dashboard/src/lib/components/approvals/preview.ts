/**
 * Tool-templated argument previews for pending calls.
 *
 * Raw JSON reads as noise; operators need to see the *shape* of what they
 * are about to approve. Each tool_name gets its own templating so a
 * ``shell`` call reads like the command it's running and a ``write_file``
 * call reads as a destination + size hint. Filesystem paths truncate
 * from the head so the destination (the safety-critical tail) stays
 * visible.
 */

const MAX_LEN = 80;

export function previewOf(toolName: string, args: Record<string, unknown>): string {
	const raw = rawPreview(toolName, args);
	return truncateHead(raw, MAX_LEN);
}

function rawPreview(toolName: string, args: Record<string, unknown>): string {
	const a = args ?? {};
	const name = toolName.toLowerCase();

	if (name === 'shell' || name === 'exec' || name === 'bash') {
		const cmd = asString(a.command) ?? asString(a.script);
		if (cmd) return cmd;
	}
	if (name === 'write_file' || name === 'fs.write' || name === 'create_file') {
		const path = asString(a.path) ?? asString(a.destination);
		const content = asString(a.content);
		const size = content !== null ? ` (${formatBytes(bytesOf(content))})` : '';
		if (path) return `→ ${path}${size}`;
	}
	if (name === 'read_file' || name === 'fs.read') {
		const path = asString(a.path);
		if (path) return `← ${path}`;
	}
	if (name === 'delete_file' || name === 'fs.delete') {
		const path = asString(a.path);
		if (path) return `✕ ${path}`;
	}
	if (name === 'http_post' || name === 'http_get' || name === 'http_put' || name === 'http_delete' || name === 'http') {
		const url = asString(a.url);
		const method = name === 'http' ? (asString(a.method) ?? 'GET').toUpperCase() : name.replace('http_', '').toUpperCase();
		if (url) {
			try {
				const u = new URL(url);
				return `${method} ${u.host}${u.pathname}`;
			} catch {
				return `${method} ${url}`;
			}
		}
	}
	if (name === 'search' || name === 'web_search') {
		const q = asString(a.query) ?? asString(a.q);
		if (q) return `? ${q}`;
	}
	if (name === 'python' || name === 'python_exec') {
		const code = asString(a.code) ?? asString(a.script);
		if (code) return code.split('\n')[0] ?? code;
	}

	// Fallback: join the first few keys as `k=v, k=v`.
	const entries = Object.entries(a).slice(0, 3);
	if (entries.length === 0) return '(no args)';
	return entries.map(([k, v]) => `${k}=${compact(v)}`).join(', ');
}

function asString(value: unknown): string | null {
	return typeof value === 'string' ? value : null;
}

function bytesOf(text: string): number {
	try {
		return new Blob([text]).size;
	} catch {
		return text.length;
	}
}

function formatBytes(n: number): string {
	if (n < 1024) return `${n} B`;
	if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
	return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

function compact(v: unknown): string {
	if (typeof v === 'string') return v.length > 30 ? v.slice(0, 29) + '…' : v;
	if (typeof v === 'number' || typeof v === 'boolean' || v === null) return String(v);
	try {
		const s = JSON.stringify(v);
		return s.length > 30 ? s.slice(0, 29) + '…' : s;
	} catch {
		return '[object]';
	}
}

/** Truncate from the head so the tail (e.g. a filesystem destination) stays visible. */
function truncateHead(text: string, max: number): string {
	if (text.length <= max) return text;
	return '…' + text.slice(text.length - (max - 1));
}
