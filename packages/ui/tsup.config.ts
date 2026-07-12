import { defineConfig } from "tsup";
import { fileURLToPath } from "node:url";

const withSelectorShim = fileURLToPath(
  new URL("./src/shims/use-sync-external-store-with-selector.mjs", import.meta.url),
);

export default defineConfig({
  entry: ["src/index.ts"],
  format: ["esm"],
  dts: true,
  sourcemap: true,
  clean: true,
  treeshake: true,
  external: ["react", "react-dom", "react/jsx-runtime"],
  // recharts is bundled in so MetricChart renders without peer resolution.
  noExternal: ["recharts"],
  // recharts has no `exports` map and its `main` is CJS (which emits a runtime
  // __require("react") that dies in the browser). Prefer the ESM `module` entry
  // so react stays a clean external `import`, shared with the design _vendor react.
  esbuildOptions(options) {
    options.mainFields = ["module", "main"];
    options.conditions = ["import", "module", "browser", "default"];
  },
  // Redirect EVERY use-sync-external-store entry (shim, shim/with-selector, and
  // the cjs/*.production|development variants they require) to a pure-ESM
  // reimplementation on React 19's native hooks — removes the CJS __require("react")
  // that dies in the design bundle, keeping one shared external react.
  esbuildPlugins: [
    {
      name: "shim-use-sync-external-store",
      setup(build) {
        build.onResolve({ filter: /use-sync-external-store/ }, () => ({
          path: withSelectorShim,
        }));
      },
    },
  ],
});
