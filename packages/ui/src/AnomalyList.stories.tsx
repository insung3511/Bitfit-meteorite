import type { Meta, StoryObj } from "@storybook/react";
import { AnomalyList } from "./AnomalyList";
import { sampleAnomalies } from "./_sample";

const meta: Meta<typeof AnomalyList> = {
  title: "Composites/AnomalyList",
  component: AnomalyList,
};
export default meta;
type Story = StoryObj<typeof AnomalyList>;

export const WithAnomalies: Story = { args: { anomalies: sampleAnomalies } };
export const Empty: Story = { args: { anomalies: [] } };
