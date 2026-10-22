import { ChangeEvent, FormEvent, useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api/client";

type LegacyPreview = Awaited<ReturnType<typeof api.previewLegacyImport>>;
type Campaign = { id: string; title: string; created_at: string; updated_at: string; archived_at: null };

export function LegacyImport({ onImported, onCancel }: {
  onImported: (campaign: Campaign) => void;
  onCancel: () => void;
}) {
  const [bundle, setBundle] = useState<Record<string, unknown> | null>(null);
  const [preview, setPreview] = useState<LegacyPreview | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const keyRef = useRef(globalThis.crypto.randomUUID());
  const epochRef = useRef(0);
  const mountedRef = useRef(true);
  const importingRef = useRef(false);

  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  async function loadFile(event: ChangeEvent<HTMLInputElement>) {
    const epoch = ++epochRef.current;
    setBundle(null); setPreview(null); setConfirmed(false); setError(null);
    setBusy(false);
    keyRef.current = globalThis.crypto.randomUUID();
    const file = event.target.files?.[0];
    if (!file) return;
    try {
      if (!file.name.toLowerCase().endsWith(".json") || file.size > 20 * 1024 * 1024) {
        throw new Error("Chọn một file bundle .json riêng tư, tối đa 20 MiB.");
      }
      const data: unknown = JSON.parse(await file.text());
      if (!data || typeof data !== "object" || Array.isArray(data) ||
          (data as Record<string, unknown>).format !== "playroom_legacy_story_bundle") {
        throw new Error("Đây không phải file playroom_legacy_story_bundle. Hãy dùng Nhập ChatGPT cho conversations.json.");
      }
      if (!mountedRef.current || epoch !== epochRef.current) return;
      setBundle(data as Record<string, unknown>);
    } catch (cause) {
      if (!mountedRef.current || epoch !== epochRef.current) return;
      setError(cause instanceof Error ? cause.message : "Không đọc được file legacy.");
    }
  }

  async function doPreview() {
    if (!bundle || busy) return;
    const epoch = epochRef.current;
    const selectedBundle = bundle;
    setBusy(true); setError(null);
    try {
      const result = await api.previewLegacyImport(selectedBundle);
      if (!mountedRef.current || epoch !== epochRef.current) return;
      setPreview(result);
    } catch (cause) {
      if (!mountedRef.current || epoch !== epochRef.current) return;
      setPreview(null);
      setError(cause instanceof ApiError ? cause.message : "Bundle không hợp lệ hoặc không thể xem trước.");
    } finally {
      if (mountedRef.current && epoch === epochRef.current) setBusy(false);
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!bundle || !preview || !confirmed || busy || importingRef.current) return;
    const epoch = epochRef.current;
    const selectedBundle = bundle;
    importingRef.current = true;
    setBusy(true); setError(null);
    try {
      const saved = await api.importLegacyBundle(selectedBundle, keyRef.current);
      if (!mountedRef.current || epoch !== epochRef.current) return;
      const now = new Date().toISOString();
      onImported({ id: saved.campaign_id, title: String((selectedBundle.campaign_create_payload as {title: string}).title), created_at: now, updated_at: now, archived_at: null });
    } catch (cause) {
      if (!mountedRef.current || epoch !== epochRef.current) return;
      setError(cause instanceof ApiError ? cause.message : "Không thể lưu bundle. Dữ liệu trên thiết bị không bị thay đổi.");
    } finally {
      importingRef.current = false;
      if (mountedRef.current && epoch === epochRef.current) setBusy(false);
    }
  }

  return <section className="create-card" aria-labelledby="legacy-import-title">
    <div className="section-heading"><div><p className="eyebrow">CHUYỂN TRUYỆN CŨ</p><h2 id="legacy-import-title">Nhập Legacy Story Bundle</h2></div><button type="button" className="quiet-button touch-target" onClick={onCancel}>Đóng</button></div>
    <p>Chỉ nhập bundle riêng mà bạn tự chọn vào Playroom đang chạy. Không gửi dữ liệu tới AI khi xem trước hoặc nhập. Nếu Playroom chạy trên máy chủ khác, tệp sẽ được gửi tới máy chủ đó.</p>
    <p className="form-error">Đây là gói canon / sự kiện / checkpoint có lịch sử chưa đầy đủ. Không tự tạo lượt cũ hay chương kế tiếp.</p>
    {error && <div role="alert" className="form-error">{error}</div>}
    <div className="campaign-form">
      <label htmlFor="legacy-bundle-file">Bundle JSON (tối đa 20 MiB)</label>
      <input id="legacy-bundle-file" type="file" accept=".json,application/json" onChange={(event) => void loadFile(event)} />
      {bundle && <button type="button" className="quiet-button touch-target" disabled={busy} onClick={() => void doPreview()}>Xem cấu trúc và khoảng trống</button>}
    </div>
    {preview && <form className="campaign-form" onSubmit={(event) => void submit(event)}>
      <p role="status">Nguồn <strong>{preview.format}</strong> · v{preview.schema_version}. Nhân vật: <strong>{preview.counts.characters}</strong>, canon: <strong>{preview.counts.canon_facts}</strong>, sự kiện: <strong>{preview.counts.timeline_events}</strong>, quan hệ: <strong>{preview.counts.relationships}</strong>, trích đoạn của người chơi: <strong>{preview.counts.player_excerpts}</strong>.</p>
      <p>Chương hoàn thành: <strong>{preview.checkpoint.last_completed_chapter}</strong>; chương kế tiếp chưa viết: <strong>{preview.checkpoint.next_chapter}</strong>. Số lượt hội thoại đầy đủ có thể phát lại: <strong>{preview.turn_count}</strong>.</p>
      {preview.warnings.map((warning) => <p key={warning} className="form-error">{warning}</p>)}
      <p>Sau khi nhập, ký ức nguồn ở trạng thái chờ duyệt, Send bị khóa. Xem và chỉnh Hồ sơ / Ký ức / Cảnh trong checkpoint rồi mới bật Send. Chỉ Send khi đồng ý chia sẻ ngữ cảnh riêng cho provider đã chọn.</p>
      <label><input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} /> Tôi hiểu đây không phải toàn bộ lịch sử, còn thiếu canon chưa kiểm chứng, và nhập không đồng nghĩa cho phép AI nhận dữ liệu.</label>
      <button className="primary-button touch-target" type="submit" disabled={!confirmed || busy}>{busy ? "Đang lưu…" : "Tạo chiến dịch nháp để duyệt"}</button>
    </form>}
  </section>;
}
