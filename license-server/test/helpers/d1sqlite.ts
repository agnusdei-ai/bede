/**
 * A D1Database test double over REAL SQLite (better-sqlite3), loaded with the
 * real migration file. The license-server's idempotency story rests on
 * SQLite semantics — unique constraints, `on conflict do nothing`, scalar
 * `max()` — so the tests run the same SQL the Worker runs against a real
 * engine, not an emulation of it.
 *
 * Only the surface src/ uses is implemented: prepare → bind → run/first/all.
 * The cast is confined here; production code keeps its honest D1Database
 * type.
 */

import Database from "better-sqlite3";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const MIGRATION_PATH = fileURLToPath(
  new URL("../../migrations/0001_init.sql", import.meta.url),
);

export function createTestD1(): D1Database {
  const sqlite = new Database(":memory:");
  sqlite.exec(readFileSync(MIGRATION_PATH, "utf-8"));

  return {
    prepare: (sql: string) => {
      const stmt = sqlite.prepare(sql);
      return {
        bind: (...params: unknown[]) => ({
          run: () => {
            const info = stmt.run(...(params as never[]));
            return { meta: { changes: info.changes } };
          },
          first: <T>() => (stmt.get(...(params as never[])) as T | undefined) ?? null,
          all: () => ({ results: stmt.all(...(params as never[])) }),
        }),
      };
    },
  } as unknown as D1Database;
}
