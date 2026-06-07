import { initTelemetry } from '$lib/telemetry';

/** Initialize anonymous, opt-in telemetry once on client boot (no-op until consented). */
export const init = () => {
	initTelemetry();
};
