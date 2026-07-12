import type { Meta, StoryObj } from "@storybook/react";
import { StatTile } from "./StatTile";
import { MetricChart } from "./MetricChart";
import { samplePoints } from "./_sample";

const meta: Meta<typeof StatTile> = {
  title: "Data/StatTile",
  component: StatTile,
};
export default meta;
type Story = StoryObj<typeof StatTile>;

export const Light: Story = {
  args: {
    label: "Resting HR",
    value: "62",
    unit: "bpm",
    caption: "7-day average",
    accent: "var(--series-1)",
  },
};

export const Dark: Story = {
  args: {
    label: "Steps",
    value: "8,647",
    caption: "Today",
    accent: "var(--series-3)",
    tone: "dark",
  },
};

export const WithChart: Story = {
  args: {
    label: "Resting HR",
    value: "62",
    unit: "bpm",
    accent: "var(--series-1)",
    chart: (
      <MetricChart label="rhr" color="var(--series-1)" points={samplePoints} chartType="area" embedded />
    ),
  },
};

export const TileRow: Story = {
  render: () => (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      <StatTile tone="dark" label="Steps" value="8,647" accent="var(--series-3)" />
      <StatTile tone="dark" label="Resting HR" value="62" unit="bpm" accent="var(--series-1)" />
      <StatTile tone="dark" label="Sleep" value="7.4" unit="h" accent="var(--series-5)" />
      <StatTile tone="dark" label="Energy" value="428" unit="kcal" accent="var(--series-4)" />
    </div>
  ),
};
