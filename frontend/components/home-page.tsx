"use client";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

import { ArrowRightIcon, BoltIcon, CodeIcon, FlaskIcon } from "@/components/icons";
import { Logo } from "@/components/logo";
import { createSandbox } from "@/lib/api";
import { formatError } from "@/lib/format";

const previewRows: Array<{
  direction: "out" | "in";
  text: string;
  badge?: string;
  time?: string;
}> = [
  { direction: "out", text: "GET /users" },
  { direction: "in", text: '{"users": [], "count": 0}', badge: "200 OK", time: "42ms" },
  { direction: "out", text: "POST /users" },
  { direction: "in", text: '{"id": 1, "name": "Alice Chen"}', badge: "201", time: "67ms" },
  { direction: "out", text: "GET /users/1" },
  { direction: "in", text: '{"id": 1, "name": "Alice Chen", "email": "..."}', badge: "200 OK", time: "38ms" },
] as const;

const features = [
  {
    icon: <BoltIcon className="feature-card__icon-svg" />,
    title: "Ready in 5 seconds",
    body: "Instantly provision a FastAPI + SQLite environment. No config, no waiting.",
  },
  {
    icon: <CodeIcon className="feature-card__icon-svg" />,
    title: "Live route editing",
    body: "Edit your API routes directly in the browser. Changes apply in real time.",
  },
  {
    icon: <FlaskIcon className="feature-card__icon-svg" />,
    title: "Built-in API tester",
    body: "Send requests and inspect responses without leaving the sandbox.",
  },
] as const;

export function HomePage() {
  const router = useRouter();
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isRouting, startTransition] = useTransition();

  async function handleCreateSandbox() {
    if (creating) {
      return;
    }

    setCreating(true);
    setError(null);

    try {
      const sandbox = await createSandbox();
      startTransition(() => {
        router.push(sandbox.url);
      });
    } catch (caughtError) {
      setError(formatError(caughtError));
      setCreating(false);
    }
  }

  return (
    <main className="home-page">
        <div className="home-page__glow" />
        <div className="home-page__grid" />
        <div className="layout-width">
          <header className="home-nav">
            <Logo />
          </header>

          <section className="hero">
            <div className="hero__eyebrow">
              <span className="hero__eyebrow-dot" />
              Instant FastAPI + SQLite sandboxes
            </div>
            <h1 className="hero__title">
              Spin up a backend
              <span className="hero__title-accent">in seconds</span>
            </h1>
            <p className="hero__body">
              Edit API routes live. Test endpoints instantly. No setup, no infrastructure, no noise.
            </p>
            <button className="button button--hero" type="button" onClick={handleCreateSandbox} disabled={creating || isRouting}>
              {creating || isRouting ? "Starting sandbox..." : "Create Sandbox"}
              <ArrowRightIcon className="button__icon" />
            </button>
            {error ? <p className="hero__error">{error}</p> : null}
            <div className="hero__stats">
              <span>
                <strong>2,400+</strong> sandboxes created
              </span>
              <span className="hero__divider" />
              <span>
                avg. <strong>1.8s</strong> startup
              </span>
              <span className="hero__divider" />
              <span>
                <strong>Free</strong> forever
              </span>
            </div>
          </section>

          <section className="preview-terminal" aria-label="Sandbox preview">
            <div className="preview-terminal__header">
              <div className="preview-terminal__lights">
                <span className="preview-terminal__light preview-terminal__light--red" />
                <span className="preview-terminal__light preview-terminal__light--amber" />
                <span className="preview-terminal__light preview-terminal__light--green" />
              </div>
              <div className="preview-terminal__tag">
                <span>sandbox:</span>
                <strong>sb-f7a92c1d</strong>
              </div>
              <div className="preview-terminal__live">
                <span className="preview-terminal__live-dot" />
                live
              </div>
            </div>
            <div className="preview-terminal__body">
              {previewRows.map((row) => (
                <div key={`${row.direction}-${row.text}`} className="preview-terminal__row">
                  <span className={row.direction === "out" ? "preview-terminal__arrow preview-terminal__arrow--out" : "preview-terminal__arrow"}>
                    {row.direction === "out" ? "→" : "←"}
                  </span>
                  <span className="preview-terminal__text">{row.text}</span>
                  {row.badge ? <span className="preview-terminal__badge">{row.badge}</span> : null}
                  {row.time ? <span className="preview-terminal__time">{row.time}</span> : null}
                </div>
              ))}
            </div>
          </section>
        </div>

        <section className="feature-strip" id="features">
          <div className="layout-width feature-strip__inner">
            {features.map((feature) => (
              <article key={feature.title} className="feature-card">
                <div className="feature-card__icon">{feature.icon}</div>
                <h2 className="feature-card__title">{feature.title}</h2>
                <p className="feature-card__body">{feature.body}</p>
              </article>
            ))}
          </div>
        </section>

        <footer className="footer" id="footer">
          <div className="layout-width footer__inner">
            <span>© 2026 Spinbox. Built for developers.</span>
            <div className="footer__links">
              <a href="#footer">Privacy</a>
              <a href="#footer">Terms</a>
              <a href="#footer">Status</a>
            </div>
          </div>
        </footer>
    </main>
  );
}
