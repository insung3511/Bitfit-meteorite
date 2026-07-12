import type { Meta, StoryObj } from "@storybook/react";
import { Badge } from "./Badge";

const meta: Meta<typeof Badge> = {
  title: "Data/Badge",
  component: Badge,
};
export default meta;
type Story = StoryObj<typeof Badge>;

export const Pill: Story = { args: { children: "Sleep", color: "var(--series-5)" } };
export const Bullet: Story = { args: { variant: "bullet", children: "7", color: "var(--series-6)" } };

export const Palette: Story = {
  render: () => (
    <div className="flex flex-wrap items-center gap-2">
      {["Steps", "Heart", "Sleep", "Weight", "Energy", "Stress"].map((label, i) => (
        <Badge key={label} color={`var(--series-${i + 1})`}>
          {label}
        </Badge>
      ))}
    </div>
  ),
};
