import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { routes } from "@/lib/routes";

const backendUrl = (process.env.BACKEND_URL ?? "http://localhost:8000").replace(/\/+$/, "");

export async function hasAuthenticatedSession() {
  const cookieHeader = (await cookies()).toString();
  if (!cookieHeader) return false;

  try {
    const response = await fetch(`${backendUrl}/api/auth/me`, {
      headers: { cookie: cookieHeader },
      cache: "no-store",
    });
    return response.ok;
  } catch {
    return false;
  }
}

export async function redirectAuthenticatedUser() {
  if (await hasAuthenticatedSession()) {
    redirect(routes.workspaces);
  }
}
