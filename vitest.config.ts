import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["test/**/*.test.ts", "src/testkit/**/*.test.ts"],
    // PostgreSQL integration suites use the same disposable TEST_DATABASE_URL.
    // Running files concurrently lets one suite claim or resolve another suite's
    // fixture between assertions, making the backend gate nondeterministic.
    fileParallelism: false,
  },
});
