import type { Metadata } from "next";
import { PlannerApp } from "./_components/planner-app";

export const metadata: Metadata = { title: "Planificateur · Fedi's Planner" };

export default function PlannerPage() {
  return <PlannerApp />;
}
