"use client";

import { FormEvent, ReactNode, useEffect, useState } from "react";
import { ApiRequestError, getCurrentUser, login, register } from "@/lib/api";
import type { AuthenticatedUser } from "@/lib/types";

type Mode = "login" | "register";

export function AuthGate({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthenticatedUser | null>(null);
  const [checked, setChecked] = useState(false);

  useEffect(() => {
    void getCurrentUser()
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setChecked(true));
  }, []);

  if (!checked) return <main className="auth-loading" aria-live="polite">正在确认工作区身份...</main>;
  if (!user) return <AuthenticationForm onAuthenticated={setUser} />;
  return <>{children}</>;
}

function AuthenticationForm({ onAuthenticated }: { onAuthenticated: (user: AuthenticatedUser) => void }) {
  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!email.trim() || password.length < 10) {
      setError("请输入有效邮箱和至少 10 位密码。");
      return;
    }
    setLoading(true);
    setError("");
    try {
      onAuthenticated(
        mode === "login"
          ? await login(email.trim(), password)
          : await register(email.trim(), password)
      );
    } catch (caught) {
      setError(
        caught instanceof ApiRequestError && caught.status === 401
          ? "邮箱或密码不正确。"
          : caught instanceof Error ? caught.message : "无法完成身份验证。"
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="auth-shell">
      <section className="auth-intro" aria-labelledby="auth-title">
        <span className="auth-mark">MP</span>
        <p className="kicker">Private workspace</p>
        <h1 id="auth-title">Market Pilot</h1>
        <p>餐饮经营数据、报告和追问记录仅在你的工作区内可见。</p>
      </section>
      <section className="auth-form-surface" aria-label="账户验证">
        <div className="auth-mode" role="tablist" aria-label="账户操作">
          <button aria-selected={mode === "login"} className={mode === "login" ? "is-active" : ""} onClick={() => setMode("login")} role="tab" type="button">登录</button>
          <button aria-selected={mode === "register"} className={mode === "register" ? "is-active" : ""} onClick={() => setMode("register")} role="tab" type="button">创建账户</button>
        </div>
        <form onSubmit={submit}>
          <h2>{mode === "login" ? "进入工作区" : "创建个人工作区"}</h2>
          <label htmlFor="auth-email">邮箱</label>
          <input autoComplete="email" id="auth-email" onChange={(event) => setEmail(event.target.value)} type="email" value={email} />
          <label htmlFor="auth-password">密码</label>
          <input autoComplete={mode === "login" ? "current-password" : "new-password"} id="auth-password" minLength={10} onChange={(event) => setPassword(event.target.value)} type="password" value={password} />
          {error ? <p className="auth-error" role="alert">{error}</p> : null}
          <button disabled={loading} type="submit">{loading ? "正在验证..." : mode === "login" ? "登录" : "创建并进入"}</button>
        </form>
      </section>
    </main>
  );
}
