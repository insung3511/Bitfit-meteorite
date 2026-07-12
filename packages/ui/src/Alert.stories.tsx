import type { Meta, StoryObj } from "@storybook/react";
import { Alert } from "./Alert";

const meta: Meta<typeof Alert> = {
  title: "Feedback/Alert",
  component: Alert,
};
export default meta;
type Story = StoryObj<typeof Alert>;

export const Error: Story = {
  args: { tone: "error", children: "Could not reach the backend at http://localhost:8000." },
};
export const Info: Story = {
  args: { tone: "info", children: "No data synced yet — import a Google Takeout export to begin." },
};
