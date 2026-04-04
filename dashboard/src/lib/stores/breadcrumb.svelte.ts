export interface Crumb {
	label: string;
	href?: string;
}

let crumbs = $state<Crumb[]>([]);

export function setCrumbs(items: Crumb[]): void {
	crumbs = items;
}

export function getCrumbs(): Crumb[] {
	return crumbs;
}
