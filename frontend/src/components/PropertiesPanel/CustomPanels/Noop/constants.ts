/**
 * Attribute key names for the `noop` operator.
 *
 * These must exactly match the backend attribute keys returned by
 * `NOOPOperator.get_metadata()["attributes"]` once that is implemented.
 * Used as the `name` argument to `controller.getPropertyValue()` /
 * `controller.updatePropertyValue()` throughout the panel.
 */
export const NOOP_ATTRIBUTE = {
  /** Seconds to sleep before passing data through */
  SLEEP_SEC: 'sleep_sec',
} as const;

/**
 * Union type of all valid `noop` attribute key strings.
 */
export type NoopAttributeKey = typeof NOOP_ATTRIBUTE[keyof typeof NOOP_ATTRIBUTE];

/**
 * Frontend fallback defaults, used when operator metadata does not yet expose
 * an `attributes` block. These match the Python-side defaults in NOOPOperator.
 */
export const NOOP_DEFAULTS = {
  SLEEP_SEC: 0,
} as const;
