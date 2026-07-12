import type { Meta, StoryObj } from "@storybook/react";
import { Card } from "./Card";

const meta: Meta<typeof Card> = {
  title: "Surfaces/Card",
  component: Card,
};
export default meta;
type Story = StoryObj<typeof Card>;

export const Basic: Story = {
  args: {
    title: "Resting heart rate",
    subtitle: "30-day rolling view",
    children: <p className="text-sm text-black/60 dark:text-white/60">Card body content.</p>,
  },
};

export const Selected: Story = {
  args: {
    title: "Selected panel",
    subtitle: "Click state",
    selected: true,
    onClick: () => {},
    children: <p className="text-sm text-black/60 dark:text-white/60">Highlighted surface.</p>,
  },
};
