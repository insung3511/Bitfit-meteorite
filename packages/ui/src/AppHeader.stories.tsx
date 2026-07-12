import type { Meta, StoryObj } from "@storybook/react";
import { AppHeader } from "./AppHeader";
import { Button } from "./Button";

const meta: Meta<typeof AppHeader> = {
  title: "Navigation/AppHeader",
  component: AppHeader,
  parameters: { layout: "fullscreen" },
};
export default meta;
type Story = StoryObj<typeof AppHeader>;

export const Default: Story = {
  args: {
    brand: "Health Assistant",
    links: [
      { label: "Chat", href: "#chat" },
      { label: "Dashboard", href: "#dashboard" },
    ],
    right: <Button variant="ghost">Log out</Button>,
  },
};
