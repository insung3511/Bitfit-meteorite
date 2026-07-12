import type { Meta, StoryObj } from "@storybook/react";
import { Button } from "./Button";

const meta: Meta<typeof Button> = {
  title: "Controls/Button",
  component: Button,
  args: { children: "Get sleep coaching" },
};
export default meta;
type Story = StoryObj<typeof Button>;

export const Solid: Story = { args: { variant: "solid" } };
export const Outline: Story = { args: { variant: "outline", children: "Add signal" } };
export const Ghost: Story = { args: { variant: "ghost", children: "Log out" } };
export const Disabled: Story = { args: { variant: "solid", disabled: true } };

export const AllVariants: Story = {
  render: () => (
    <div className="flex items-center gap-3">
      <Button variant="solid">Primary</Button>
      <Button variant="outline">Secondary</Button>
      <Button variant="ghost">Ghost</Button>
    </div>
  ),
};
