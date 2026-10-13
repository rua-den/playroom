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
        <div className="brand-mark" aria-hidden="true">✦</div>
        <p className="eyebrow">PLAYROOM / PRIVATE STORY SPACE</p>
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
        <p className="security-note">Mật khẩu chỉ được gửi khi đăng nhập và phiên dùng cookie HttpOnly. Dữ liệu riêng trong bộ nhớ trình duyệt được xóa khi bạn đăng xuất.</p>
      </section>
    </main>
  );
}
