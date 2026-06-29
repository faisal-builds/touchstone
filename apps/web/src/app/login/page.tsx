"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import * as React from "react";

import { Button } from "@/components/ui/primitives";
import { Field, FormError, Input } from "@/components/ui/form";
import { AuthShell } from "@/components/layout/auth-shell";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [orgSlug, setOrgSlug] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const res = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ email, password, org_slug: orgSlug || undefined }),
    });
    if (res.ok) {
      const next = new URLSearchParams(window.location.search).get("next");
      router.push(next || "/dashboard");
      router.refresh();
      return;
    }
    const body = await res.json().catch(() => ({}));
    setError(body.detail || body.title || "Those credentials didn't work. Try again.");
    setBusy(false);
  }

  return (
    <AuthShell title="Sign in" subtitle="Access your verification workspace.">
      <form onSubmit={submit} className="space-y-4">
        <FormError>{error}</FormError>
        <Field label="Email" htmlFor="email">
          <Input id="email" type="email" autoComplete="email" required
            value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@company.com" />
        </Field>
        <Field label="Password" htmlFor="password">
          <Input id="password" type="password" autoComplete="current-password" required
            value={password} onChange={(e) => setPassword(e.target.value)} placeholder="••••••••" />
        </Field>
        <Field label="Organization" htmlFor="org" hint="optional">
          <Input id="org" value={orgSlug} mono
            onChange={(e) => setOrgSlug(e.target.value)} placeholder="acme" />
        </Field>
        <Button type="submit" disabled={busy} className="w-full">
          {busy ? "Signing in…" : "Sign in"}
        </Button>
      </form>
      <p className="mt-6 text-center text-[13px] text-muted">
        New to Touchstone?{" "}
        <Link href="/signup" className="font-medium text-ink underline-offset-2 hover:underline">
          Create an organization
        </Link>
      </p>
    </AuthShell>
  );
}
