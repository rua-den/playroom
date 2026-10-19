import { FormEvent, useState } from "react";
import { api, ApiError } from "../../api/client";
import type { Owner } from "../../api/types";

interface AuthViewProps {
  onAuthenticated: (owner: Owner) => void;
  notice?: string | null;
}

export function AuthView({ onAuthenticated, notice }: AuthViewProps) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setError(null);
    try {
      const result = await api.login({ email, password });
      onAuthenticated(result.owner);
    } catch (cause) {
      setError(cause instanceof ApiError && cause.status === 401
        ? "Email hoặc mật khẩu không đúng."
        : "Không thể kết nối tới Playroom.");
    } finally {
      setPending(false);
    }
  }

  return (
    <main className="auth-layout">
      <section className="auth-card" aria-labelledby="login-title">
        <div className="brand-mark" aria-hidden="true"><svg viewBox="0 0 24 24" width="25" height="25" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><path d="M4 5.5c3.2-.8 5.9-.1 8 1.9v12c-2.1-2-4.8-2.7-8-1.9z"/><path d="M20 5.5c-3.2-.8-5.9-.1-8 1.9v12c2.1-2 4.8-2.7 8-1.9z"/><path d="M7 9h2M15 9h2M7 12h2M15 12h2"/></svg></div>
        <p className="eyebrow">PLAYROOM</p>
        <h1 id="login-title">Đăng nhập Playroom</h1>
        <p className="auth-intro">Một căn phòng riêng cho những câu chuyện còn đang tiếp diễn.</p>
        {notice && <div role="alert" className="form-error">{notice}</div>}
        <form onSubmit={submit} className="auth-form">
          <label htmlFor="email">Email</label>
          <input id="email" type="email" autoComplete="username" value={email} onChange={(event) => setEmail(event.target.value)} required />
          <label htmlFor="password">Mật khẩu</label>
          <input id="password" type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} required />
          {error && <div role="alert" className="form-error">{error}</div>}
          <button type="submit" className="primary-button" disabled={pending}>{pending ? "Đang xác thực…" : "Đăng nhập"}</button>
        </form>
        <p className="security-note">Dùng tài khoản bạn đã tạo khi khởi chạy Playroom.</p>
      </section>
    </main>
  );
}
