export function formatCost(usd: number | null): string {
	if (usd === null) return 'N/A';
	if (usd === 0) return '$0';
	if (usd < 0.01) return `$${usd.toFixed(4)}`;
	return `$${usd.toFixed(2)}`;
}
