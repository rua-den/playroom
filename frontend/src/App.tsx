import { useEffect, useState } from "react";
import { api, ApiError, getAuthGeneration, privateCache, subscribeAuthExpired } from "./api/client";
import type { Owner } from "./api/types";
import { AppShell } from "./components/AppShell";
import { AuthView } from "./features/auth/AuthView";
import "./styles.css";

function clearGenerationIdentities() {
  for (let index = localStorage.length - 1; index >= 0; index -= 1) {
    const key = localStorage.key(index);
    if (key?.startsWith("playroom:generation:")) localStorage.removeItem(key);
  }
  try {
    for (let index = sessionStorage.length - 1; index >= 0; index -= 1) {
      const key = sessionStorage.key(index);
      if (key?.startsWith("playroom:action-draft:")) sessionStorage.removeItem(key);
    }
  } catch { /* Logout still clears server and in-memory state when storage is blocked. */ }
}

export default function App() {
  const [owner, setOwner] = useState<Owner | null>(null);
  const [booting, setBooting] = useState(true);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    api.me({ notifyAuthExpired: false }).then((result) => {
      if (active) setOwner(result);
    }).catch((cause) => {
      if (active && !(cause instanceof ApiError && cause.status === 401)) setOwner(null);
    }).finally(() => { if (active) setBooting(false); });
    return () => { active = false; };
  }, []);

  useEffect(() => subscribeAuthExpired(() => {
    privateCache.clear();
    clearGenerationIdentities();
    setOwner(null);
    setNotice("Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.");
  }), []);

  async function logout() {
    privateCache.clear();
    clearGenerationIdentities();
    setOwner(null);
    setNotice(null);
    void api.logout().then((result) => {
      if (!result.ok && getAuthGeneration() === result.generation) {
        setNotice("Đã xóa dữ liệu riêng trên thiết bị, nhưng chưa xác nhận được đăng xuất trên máy chủ.");
      }
    });
  }

  if (booting) return <div className="loading-screen" role="status">Đang mở Playroom…</div>;
  return owner ? <AppShell owner={owner} onLogout={logout} notice={notice} /> : <AuthView onAuthenticated={(nextOwner) => { setNotice(null); setOwner(nextOwner); }} notice={notice} />;
}
