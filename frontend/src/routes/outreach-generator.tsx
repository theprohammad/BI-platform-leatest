/**
 * Outreach has been unified into Lead Intelligence (Sales). This route now
 * redirects there so old links keep working while there is a single outreach
 * surface inside the lead workflow.
 */
import { createFileRoute, redirect } from "@tanstack/react-router";

export const Route = createFileRoute("/outreach-generator")({
  beforeLoad: () => {
    throw redirect({ to: "/lead-generation" });
  },
});
