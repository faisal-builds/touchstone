import { redirect } from "next/navigation";

export default function Index() {
  // The middleware sends unauthenticated users to /login; authenticated users
  // continue to the dashboard.
  redirect("/dashboard");
}
