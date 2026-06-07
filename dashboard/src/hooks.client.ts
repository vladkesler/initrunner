import { initTelemetry } from '$lib/telemetry';

/** Initialize anonymous, opt-out telemetry once on client boot. */
export const init = () => {
	initTelemetry();
};
