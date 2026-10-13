import type { Owner } from "../api/types";

interface AppShellProps {
  owner: Owner;
  onLogout: () => void;
  notice?: string | null;
}

export function AppShell({ owner, onLogout, notice }: AppShellProps) {
  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="wordmark"><span className="brand-mark small" aria-hidden="true">✦</span><span>Playroom</span></div>
        <div className="account-menu">
          <span className="account-email">{owner.email}</span>
          <button type="button" className="quiet-button" onClick={onLogout}>Đăng xuất</button>
        </div>
      </header>
      <section className="welcome-panel" aria-labelledby="welcome-title">
        {notice && <div role="alert" className="form-error shell-notice">{notice}</div>}
        <div className="welcome-copy">
          <p className="eyebrow">PHÒNG VIẾT RIÊNG</p>
          <h1 id="welcome-title">Chào mừng trở lại</h1>
          <p>Những chương truyện, ký ức đã duyệt và các nhánh lựa chọn của bạn sẽ ở cùng một nơi.</p>
        </div>
        <div className="empty-state" aria-label="Khu vực truyện đang được chuẩn bị">
          <span className="empty-icon" aria-hidden="true">⌁</span>
          <h2>Sẵn sàng mở một câu chuyện</h2>
          <p>Không có lượt chơi nào được tự động gửi. Khi bạn tạo chiến dịch, Playroom sẽ giữ nguyên quyền quyết định của bạn.</p>
        </div>
      </section>
    </main>
  );
}
