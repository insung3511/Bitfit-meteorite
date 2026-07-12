import type { Meta, StoryObj } from "@storybook/react";
import { WorkspacePanel } from "./WorkspacePanel";
import { samplePanel, samplePoints } from "./_sample";

const meta: Meta<typeof WorkspacePanel> = {
  title: "Composites/WorkspacePanel",
  component: WorkspacePanel,
  args: { panel: samplePanel, points: samplePoints },
};
export default meta;
type Story = StoryObj<typeof WorkspacePanel>;

export const Default: Story = {};
export const Selected: Story = { args: { selected: true } };
export const Loading: Story = { args: { points: null } };
