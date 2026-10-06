import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { routes } from "@/lib/routes";

export const metadata: Metadata = {
  title: "Account | Cortex",
  description: "Manage your Cortex account.",
};

export default function AccountPage() {
  redirect(routes.workspaces);
}
