import { defineConfig } from "tsup";

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
});
