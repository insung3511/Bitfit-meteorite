import type { Meta, StoryObj } from "@storybook/react";
import { Input } from "./Input";

const meta: Meta<typeof Input> = {
  title: "Controls/Input",
  component: Input,
  args: { placeholder: "Password" },
};
export default meta;
type Story = StoryObj<typeof Input>;

export const Default: Story = {};
export const Invalid: Story = { args: { invalid: true, defaultValue: "wrong" } };
export const Disabled: Story = { args: { disabled: true, defaultValue: "locked" } };
