"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import * as React from "react";

import { AuthShell } from "@/components/layout/auth-shell";
import { Button } from "@/components/ui/primitives";
import { Field, FormError, Input } from "@/components/ui/form";

function slugify(s: string): string {
  return s.toLowerCase().trim().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 40);
}

export default function SignupPage() {
  const router = useRouter();
  const [form, setForm] = React.useState({
    full_name: "", email: "", password: "", org_name: "", org_slug: "",
  });
  const [slugTouched, setSlugTouched] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);

  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));

  const orgSlug = slugTouched ? form.org_slug : slugify(form.org_name);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const res = await fetch("/api/auth/signup", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ ...form, org_slug: orgSlug }),
    });
    if (res.ok) {
      router.push("/dashboard");
      router.refresh();
      return;
    }
    const body = await res.json().catch(() => ({}));
    setError(body.detail || body.title || "Couldn't create the organization. Try again.");
    setBusy(false);
  }

  return (
    <AuthShell title="Create your organization" subtitle="Set up a workspace and your first user.">
      <form onSubmit={submit} className="space-y-4">
        <FormError>{error}</FormError>
        <Field label="Your name" htmlFor="name">
          <Input id="name" value={form.full_name} onChange={set("full_name")} placeholder="Ada Lovelace" />
        </Field>
        <Field label="Work email" htmlFor="email">
          <Input id="email" type="email" required autoComplete="email"
            value={form.email} onChange={set("email")} placeholder="you@company.com" />
        </Field>
        <Field label="Password" htmlFor="password" hint="min. 8 characters">
          <Input id="password" type="password" required minLength={8} autoComplete="new-password"
            value={form.password} onChange={set("password")} placeholder="••••••••" />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Organization" htmlFor="org">
            <Input id="org" required value={form.org_name} onChange={set("org_name")} placeholder="Acme" />
          </Field>
          <Field label="URL slug" htmlFor="slug">
            <Input id="slug" required mono value={orgSlug}
              onChange={(e) => { setSlugTouched(true); setForm((f) => ({ ...f, org_slug: e.target.value })); }}
              placeholder="acme" />
          </Field>
        </div>
        <Button type="submit" disabled={busy} className="w-full">
          {busy ? "Creating…" : "Create organization"}
        </Button>
      </form>
      <p className="mt-6 text-center text-[13px] text-muted">
        Already have an account?{" "}
        <Link href="/login" className="font-medium text-ink underline-offset-2 hover:underline">
          Sign in
        </Link>
      </p>
    </AuthShell>
  );
}
