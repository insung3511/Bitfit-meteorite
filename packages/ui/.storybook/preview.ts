import type { Preview } from "@storybook/react";
import "../src/styles.css";

const preview: Preview = {
  parameters: {
    controls: { matchers: { color: /(background|color)$/i, date: /Date$/i } },
    backgrounds: {
      default: "surface",
      values: [
        { name: "surface", value: "#ffffff" },
        { name: "dark", value: "#0a0a0a" },
      ],
    },
  },
};

export default preview;
