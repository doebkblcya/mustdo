import type { FormEvent } from "react";

type AuthMode = "login" | "register";

interface AuthPageProps {
  mode: AuthMode;
  error: string;
  onModeChange: (mode: AuthMode) => void;
  onSubmit: (payload: Record<string, FormDataEntryValue>) => Promise<void>;
}

export function AuthPage({ mode, error, onModeChange, onSubmit }: AuthPageProps) {
  const isRegister = mode === "register";

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await onSubmit(Object.fromEntries(new FormData(event.currentTarget).entries()));
  }

  return (
    <main className="auth-screen">
      <section className="auth-panel">
        <h1>Todo Analyzer</h1>
        <div className="auth-tabs">
          <button
            type="button"
            className={!isRegister ? "active" : ""}
            onClick={() => onModeChange("login")}
          >
            登录
          </button>
          <button
            type="button"
            className={isRegister ? "active" : ""}
            onClick={() => onModeChange("register")}
          >
            注册
          </button>
        </div>
        <form className="auth-form" onSubmit={handleSubmit}>
          <input className="field" name="username" autoComplete="username" placeholder="用户名" required />
          <input
            className="field"
            name="password"
            type="password"
            autoComplete={isRegister ? "new-password" : "current-password"}
            placeholder={isRegister ? "密码，至少 8 位" : "密码"}
            required
          />
          {isRegister ? (
            <input className="field" name="invite_code" autoComplete="one-time-code" placeholder="邀请码" required />
          ) : null}
          <div className="form-error">{error}</div>
          <button className="primary-button" type="submit">
            {isRegister ? "注册" : "登录"}
          </button>
        </form>
      </section>
    </main>
  );
}

export type { AuthMode };
