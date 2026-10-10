/**
 * Minimal D1 surface the tests (and the src they import) are type-checked
 * against when running under the node tsconfig — the shape of the three
 * members src/ actually uses. The real declarations come from
 * @cloudflare/workers-types in the main tsconfig; this mirror exists only
 * so test files that pull src code type-check under node types.
 */
declare interface D1Result<T = unknown> {
  results: T[];
  success: boolean;
  /** Real D1 always returns meta; non-optional to match workers-types. */
  meta: Record<string, unknown>;
}

/** Node's type surface lacks DOM's BufferSource; the Workers code casts to
 * it. Alias Node's own definition (concrete typed arrays + DataView +
 * ArrayBuffer) into the global slot so those files type-check here. */
declare type BufferSource = NodeJS.BufferSource;

declare interface D1PreparedStatement {
  bind(...values: unknown[]): D1PreparedStatement;
  first<T = unknown>(col?: string): Promise<T | null>;
  run<T = unknown>(): Promise<D1Result<T>>;
  all<T = unknown>(): Promise<D1Result<T>>;
}

declare interface D1Database {
  prepare(query: string): D1PreparedStatement;
  withSession(constraint?: string): D1DatabaseSession;
}

declare interface D1DatabaseSession {
  prepare(query: string): D1PreparedStatement;
}
