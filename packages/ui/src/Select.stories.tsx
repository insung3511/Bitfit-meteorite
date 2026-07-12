import type { Meta, StoryObj } from "@storybook/react";
import { Select } from "./Select";

const meta: Meta<typeof Select> = {
  title: "Controls/Select",
  component: Select,
};
export default meta;
type Story = StoryObj<typeof Select>;

const options = (
  <>
    <option value="area">Area</option>
    <option value="line">Line</option>
    <option value="bar">Bars</option>
  </>
);

export const Bare: Story = { args: { children: options, defaultValue: "area" } };
export const Labeled: Story = { args: { label: "Chart", children: options, defaultValue: "line" } };
