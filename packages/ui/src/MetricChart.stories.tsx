import type { Meta, StoryObj } from "@storybook/react";
import { MetricChart } from "./MetricChart";
import { samplePoints } from "./_sample";

const meta: Meta<typeof MetricChart> = {
  title: "Data/MetricChart",
  component: MetricChart,
  args: { label: "Resting heart rate", color: "var(--series-1)", points: samplePoints },
};
export default meta;
type Story = StoryObj<typeof MetricChart>;

export const Area: Story = { args: { chartType: "area" } };
export const Line: Story = { args: { chartType: "line", color: "var(--series-2)" } };
export const Bar: Story = { args: { chartType: "bar", color: "var(--series-3)" } };
export const WithBaseline: Story = { args: { chartType: "area", showBaseline: true } };
export const Empty: Story = { args: { points: [] } };
