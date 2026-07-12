import type { StorybookConfig } from "@storybook/react-vite";
import tailwindcss from "@tailwindcss/vite";

const config: StorybookConfig = {
  stories: ["../src/**/*.stories.@(ts|tsx)"],
  addons: [],
  framework: {
    name: "@storybook/react-vite",
    options: {},
  },
  core: { disableTelemetry: true },
  async viteFinal(cfg) {
    cfg.plugins = cfg.plugins ?? [];
    // Compile Tailwind v4 (the @import "tailwindcss" in styles.css) inside Storybook.
    cfg.plugins.push(tailwindcss());
    return cfg;
  },
};

export default config;
