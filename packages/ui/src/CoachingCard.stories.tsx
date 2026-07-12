import type { Meta, StoryObj } from "@storybook/react";
import { CoachingCard } from "./CoachingCard";

const meta: Meta<typeof CoachingCard> = {
  title: "Composites/CoachingCard",
  component: CoachingCard,
};
export default meta;
type Story = StoryObj<typeof CoachingCard>;

export const Idle: Story = { args: { state: "idle" } };
export const Loading: Story = { args: { state: "loading" } };
export const Ready: Story = {
  args: {
    state: "ready",
    text: "Your sleep averaged 7.4h over the last month, up 20 minutes from baseline. Resting heart rate stayed stable, suggesting good recovery. Aim to keep a consistent bedtime this week.",
  },
};
export const Error: Story = {
  args: { state: "error", error: "Sleep coaching is unavailable — check that ANTHROPIC_API_KEY is configured." },
};
