import { type ClassValue, clsx } from 'clsx';
import { twMerge } from 'tailwind-merge';

export type {
	WithElementRef,
	WithoutChildren,
	WithoutChild,
	WithoutChildrenOrChild
} from 'bits-ui';

export function cn(...inputs: ClassValue[]) {
	return twMerge(clsx(inputs));
}
