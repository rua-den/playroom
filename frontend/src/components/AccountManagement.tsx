import { FormEvent, useEffect, useState } from "react";
import { api } from "../api/client";
import type { AccountSummary } from "../api/types";

interface AccountManagementPageProps {
  currentOwnerId: string;
  onBack: () => void;
}

export function AccountManagementPage({ currentOwnerId, onBack }: AccountManagementPageProps) {
  const [accounts, setAccounts] = useState<AccountSummary[]>([]);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    api.listAccounts()
      .then((items) => { if (active) setAccounts(items); })
      .catch((cause: unknown) => { if (active) setError(cause instanceof Error ? cause.message : "Không tải được tài khoản."); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  function resetForm() {
    setUsername(""); setPassword(""); setEditingId(null); setError(null);
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;
    const normalizedUsername = username.trim();
    setPending(true); setError(null);
    try {
      if (editingId) {
        const updated = await api.updateAccount(editingId, { username: normalizedUsername, password: password || undefined });
        setAccounts((current) => current.map((account) => account.id === updated.id ? updated : account));
      } else {
        const created = await api.createAccount({ username: normalizedUsername, password });
        setAccounts((current) => [...current, created].sort((a, b) => a.username.localeCompare(b.username)));
      }
      resetForm();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Không lưu được tài khoản.");
    } finally {
      setPending(false);
    }
  }

  function edit(account: AccountSummary) {
    setEditingId(account.id); setUsername(account.username); setPassword(""); setError(null); setConfirmDeleteId(null);
  }

  async function remove(accountId: string) {
    if (pending) return;
    setPending(true); setError(null);
    try {
      await api.deleteAccount(accountId);
      setAccounts((current) => current.filter((account) => account.id !== accountId));
      setConfirmDeleteId(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Không xóa được tài khoản.");
    } finally {
      setPending(false);
    }
  }

  return <section className="account-page" aria-labelledby="account-page-title">
    <div className="section-heading">
      <div><p className="eyebrow">QUẢN TRỊ</p><h1 id="account-page-title">Quản lý tài khoản</h1><p className="form-hint">Tạo tài khoản riêng cho từng người. Mỗi tài khoản chỉ xem được truyện của mình.</p></div>
      <button type="button" className="quiet-button touch-target" onClick={onBack}>Quay lại truyện</button>
    </div>
    <form className="account-form" aria-label={editingId ? "Sửa tài khoản" : "Tạo tài khoản"} onSubmit={(event) => void submit(event)}>
      <label htmlFor="account-username">Tên đăng nhập</label>
      <input id="account-username" autoComplete="username" minLength={3} maxLength={32} pattern="[A-Za-z0-9][A-Za-z0-9._-]*[A-Za-z0-9]" required value={username} onChange={(event) => setUsername(event.target.value)} />
      <p className="form-hint">Dùng 3–32 chữ cái không dấu, số, dấu chấm, gạch dưới hoặc gạch ngang.</p>
      <label htmlFor="account-password">Mật khẩu</label>
      <input id="account-password" type="password" autoComplete="new-password" minLength={password || !editingId ? 12 : undefined} maxLength={1024} required={!editingId} value={password} onChange={(event) => setPassword(event.target.value)} />
      <p className="form-hint">Mật khẩu mới tối thiểu 12 ký tự. Khi sửa, để trống nếu không đổi mật khẩu.</p>
      {error && <div role="alert" className="form-error">{error}</div>}
      <div className="account-form-actions">
        <button type="submit" className="primary-button touch-target" disabled={pending}>{pending ? "Đang lưu…" : editingId ? "Lưu thay đổi" : "Tạo tài khoản"}</button>
        {editingId && <button type="button" className="quiet-button touch-target" disabled={pending} onClick={resetForm}>Hủy sửa</button>}
      </div>
    </form>
    <div className="account-table-wrap">
      <table className="account-table">
        <caption>Tài khoản Playroom</caption>
        <thead><tr><th scope="col">Tên đăng nhập</th><th scope="col">Quyền</th><th scope="col">Thao tác</th></tr></thead>
        <tbody>
          {loading && <tr><td colSpan={3}>Đang tải tài khoản…</td></tr>}
          {!loading && accounts.length === 0 && <tr><td colSpan={3}>Chưa có tài khoản.</td></tr>}
          {accounts.map((account) => <tr key={account.id}>
            <th scope="row">{account.username}</th>
            <td data-label="Quyền">{account.is_admin ? "Admin" : "Tài khoản"}</td>
            <td data-label="Thao tác"><div className="account-row-actions">
              <button type="button" className="quiet-button touch-target" disabled={pending} aria-label={`Sửa ${account.username}`} onClick={() => edit(account)}>Sửa</button>
              {account.id !== currentOwnerId && <button type="button" className="danger-button touch-target" disabled={pending} aria-label={`Xóa ${account.username}`} onClick={() => { setConfirmDeleteId(account.id); setError(null); }}>Xóa</button>}
            </div>{confirmDeleteId === account.id && <div className="account-delete-confirmation"><p role="status">Xóa tài khoản này sẽ xóa toàn bộ truyện và dữ liệu của tài khoản đó.</p><button type="button" className="danger-button touch-target" disabled={pending} onClick={() => void remove(account.id)}>{pending ? "Đang xóa…" : `Xác nhận xóa ${account.username}`}</button><button type="button" className="quiet-button touch-target" disabled={pending} onClick={() => setConfirmDeleteId(null)}>Hủy</button></div>}</td>
          </tr>)}
        </tbody>
      </table>
    </div>
  </section>;
}
