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
  const changed = Boolean(selected && selected !== settings?.roles?.narrator?.id);

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
      setError(cause instanceof ApiError && cause.status === 409
        ? "Model đã thay đổi ở nơi khác. Hãy tải lại danh sách rồi thử lại."
        : "Không thể lưu model kể chuyện; bản nháp vẫn được giữ.");
      toast.error("Không thể lưu model kể chuyện.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="model-switcher" aria-label="Model kể chuyện">
      {error && <div role="alert" className="form-error">{error}</div>}
      <p className="details-meta">Model hiện tại</p>
      <p className="model-switcher-current">
        {current?.model_label ?? current?.model ?? settings?.roles?.narrator?.id ?? (loading ? "Đang tải…" : "Chưa ghim model")}
        {settings?.roles?.narrator && <span> · v{settings.roles.narrator.version}</span>}
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
        {profiles.map((profile) => (
          <option key={`${profile.id}-${profile.version}`} value={profile.id}>
            {profile.model_label ?? profile.model} · v{profile.version} · {profile.provider}
          </option>
        ))}
      </select>
      {settings?.policy === "free_only" && (current?.credential_tier !== "free" || current?.provider === "ollama") && (
        <p role="note" className="form-error">Free only đang bật nhưng model hiện tại không được xác minh là Free. Ollama included credits không chứng minh giới hạn chi phí; hãy mở cài đặt chi phí để tự bật Capped paid và chấp thuận ngân sách nếu cần.</p>
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
