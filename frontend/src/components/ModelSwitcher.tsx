import { useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError } from "../api/client";
import type { ModelProfileSummary, ProviderSettings } from "../api/types";
import { useToast } from "./Toast";

export function ModelSwitcher({
  open,
  onClose,
  onOpenCostSettings,
  onSaved,
  busy,
}: {
  open: boolean;
  onClose: () => void;
  onOpenCostSettings: () => void;
  onSaved: () => void;
  busy: boolean;
}) {
  const toast = useToast();
  const [settings, setSettings] = useState<ProviderSettings | null>(null);
  const [profiles, setProfiles] = useState<ModelProfileSummary[]>([]);
  const [selected, setSelected] = useState("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mounted = useRef(false);

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  useEffect(() => {
    if (!open) return;
    let active = true;
    setLoading(true);
    setError(null);
    Promise.all([api.getProviderSettings(), api.listProviderProfiles()])
      .then(([nextSettings, nextProfiles]) => {
        if (!active) return;
        setSettings(nextSettings);
        setProfiles(nextProfiles);
        setSelected(nextSettings.roles?.narrator?.id ?? "");
      })
      .catch(() => active && setError("Không thể tải danh sách model đã xác minh."))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [open]);

  const current = useMemo(
    () => profiles.find((profile) => profile.id === settings?.roles?.narrator?.id && profile.version === settings?.roles?.narrator?.version),
    [profiles, settings],
  );
  const currentDisplay = current ?? profiles.find((profile) => profile.id === settings?.roles?.narrator?.id);
  const warningProfile = current ?? currentDisplay;
  const verifiedProfiles = useMemo(() => profiles.filter(isVerifiedRealProfile), [profiles]);
  const selectedProfile = verifiedProfiles.find((profile) => profile.id === selected);
  const changed = Boolean(selectedProfile && (selectedProfile.id !== settings?.roles?.narrator?.id || selectedProfile.version !== settings?.roles?.narrator?.version));

  async function save() {
    if (!selected || !changed || busy || saving) return;
    setSaving(true);
    setError(null);
    try {
      const next = await api.updateProviderSettings({ narrator_profile_id: selected });
      if (!mounted.current) return;
      setSettings(next);
      setSelected(next.roles?.narrator?.id ?? selected);
      onSaved();
      toast.success("Đã lưu model kể chuyện cho các lượt mới.");
    } catch (cause) {
      if (!mounted.current) return;
      setError(cause instanceof ApiError && cause.status === 409
        ? "Model đã thay đổi ở nơi khác. Hãy tải lại danh sách rồi thử lại."
        : "Không thể lưu model kể chuyện; bản nháp vẫn được giữ.");
      toast.error("Không thể lưu model kể chuyện.");
    } finally {
      if (mounted.current) setSaving(false);
    }
  }

  return (
    <section className="model-switcher" aria-label="Model kể chuyện">
      {error && <div role="alert" className="form-error">{error}</div>}
      <p className="details-meta">Model hiện tại</p>
      <p className="model-switcher-current">
        {currentDisplay?.model_label ?? currentDisplay?.model ?? settings?.roles?.narrator?.id ?? (loading ? "Đang tải…" : "Chưa ghim model")}
        {settings?.roles?.narrator && <span> · ghim v{settings.roles.narrator.version}{currentDisplay && currentDisplay.version !== settings.roles.narrator.version ? ` · bản mới v${currentDisplay.version} có sẵn` : ""}</span>}
      </p>
      <p className="details-meta">Chọn một profile đã xác minh cho các lượt kể chuyện mới. Lựa chọn này không đổi chính sách chi phí hay lượt đang chạy.</p>
      <label htmlFor="chat-narrator-profile">Model narrator</label>
      <select
        id="chat-narrator-profile"
        aria-label="Model narrator"
        className="touch-target"
        value={selected}
        disabled={loading || saving || busy}
        onChange={(event) => setSelected(event.target.value)}
      >
        <option value="">Chọn model</option>
        {verifiedProfiles.map((profile) => (
          <option key={`${profile.id}-${profile.version}`} value={profile.id}>
            {profile.model_label ?? profile.model} · v{profile.version} · {profile.provider}
          </option>
        ))}
      </select>
      {verifiedProfiles.length === 0 && !loading && <p role="status">Chưa có profile narrator thật đã xác minh. Hãy mở Cài đặt để xác minh model.</p>}
      {settings?.policy === "free_only" && (warningProfile?.provider === "ollama" || selectedProfile?.provider === "ollama") && (
        <p role="note" className="form-error">Ollama included credits chưa chứng minh được cơ chế khóa chi phí của provider. Free only vẫn giữ nguyên; hãy mở Cài đặt chi phí và tự chấp thuận Capped paid nếu muốn dùng profile này.</p>
      )}
      {settings?.policy === "free_only" && warningProfile?.provider !== "ollama" && warningProfile?.credential_tier !== "free" && (
        <p role="note" className="form-error">Model hiện tại chưa được xác minh là Free. Free only sẽ chặn lượt trả phí; hãy mở Cài đặt chi phí nếu bạn muốn tự chấp thuận Capped paid.</p>
      )}
      <div className="model-switcher-actions">
        <button type="button" className="primary-button touch-target" disabled={!changed || saving || busy} onClick={save}>
          {saving ? "Đang lưu…" : "Lưu model"}
        </button>
        <button type="button" className="quiet-button touch-target" onClick={onOpenCostSettings}>Cài đặt chi phí</button>
        <button type="button" className="quiet-button touch-target" onClick={onClose}>Đóng</button>
      </div>
    </section>
  );
}

function isVerifiedRealProfile(profile: ModelProfileSummary) {
  return (profile.provider === "openrouter" || profile.provider === "ollama") &&
    profile.pricing_verified === true && profile.is_test_profile !== true;
}
