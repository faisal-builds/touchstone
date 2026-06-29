/** Await a promise, returning a fallback on any error (keeps pages resilient
 * when a backend is briefly unavailable). Returns a tuple so callers can show a
 * degraded/error state when needed. */
export async function safe<T>(p: Promise<T>, fallback: T): Promise<[T, boolean]> {
  try {
    return [await p, false];
  } catch {
    return [fallback, true];
  }
}
