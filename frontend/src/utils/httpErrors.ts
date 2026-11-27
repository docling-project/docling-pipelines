/** True when `err` is an HTTP error (e.g. an AxiosError) carrying a 409 Conflict response. */
export function isConflictError(err: unknown): boolean {
  return (err as { response?: { status?: number } } | null)?.response?.status === 409;
}
