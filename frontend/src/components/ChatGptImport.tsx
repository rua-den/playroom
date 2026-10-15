import { ChangeEvent, FormEvent, useRef, useState } from "react";
import { api, ApiError } from "../api/client";
import { ChatGptConversation, listChatGptConversations } from "../features/import/parseChatGptExport";

type Preview = Awaited<ReturnType<typeof api.previewChatGptImport>>;
interface Props {
  onImported: (campaign: { id: string; title: string; created_at: string; updated_at: string; archived_at: null }) => void;
  onCancel: () => void;
}

function makeKey() {
  return globalThis.crypto.randomUUID();
}

export function ChatGptImport({ onImported, onCancel }: Props) {
  const [conversations, setConversations] = useState<ChatGptConversation[]>([]);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [title, setTitle] = useState("");
  const [world, setWorld] = useState("Bangtan");
  const [persona, setPersona] = useState("Henn");
  const [cast, setCast] = useState("");
  const [approved, setApproved] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const keyRef = useRef(makeKey());
  const selected = conversations[selectedIndex];

  async function loadFiles(event: ChangeEvent<HTMLInputElement>) {
    setPreview(null); setError(null); setNotice(null); setApproved(false);
    keyRef.current = makeKey();
    const files = Array.from(event.target.files ?? []);
    if (!files.length) return;
    try {
      const found: ChatGptConversation[] = [];
      for (const file of files) {
        if (file.name.toLowerCase().endsWith(".zip")) {
          throw new Error("Giải nén ZIP trên thiết bị rồi chọn conversations.json (hoặc các tệp JSON được đánh số).");
        }
        if (file.size > 60 * 1024 * 1024) {
          throw new Error("JSON quá lớn để xem trên thiết bị. Hãy tách riêng thread cần nhập.");
        }
        found.push(...listChatGptConversations(await file.text()));
      }
      const seen = new Set<string>();
      const unique = found.filter((item) => {
        if (seen.has(item.id)) return false;
        seen.add(item.id);
        return true;
      });
      setConversations(unique); setSelectedIndex(0);
      setTitle(unique[0]?.title.slice(0, 160) || "Truyện nhập từ ChatGPT");
      setNotice(`Đã đọc ${unique.length} cuộc hội thoại trên thiết bị. Chưa tải nội dung lên server.`);
    } catch (cause) {
      setConversations([]);
      setError(cause instanceof Error ? cause.message : "Không thể đọc tệp export.");
    }
  }

  function choose(index: number) {
    setSelectedIndex(index);
    setPreview(null); setApproved(false); setError(null); setNotice(null);
    setTitle(conversations[index]?.title.slice(0, 160) ?? "");
    keyRef.current = makeKey();
  }

  async function doPreview() {
    if (!selected) return;
    setBusy(true); setError(null);
    try {
      const result = await api.previewChatGptImport(selected);
      setPreview(result); setNotice(null);
    } catch (cause) {
      setPreview(null);
      setError(cause instanceof ApiError ? cause.message : "Không thể xem trước thread đã chọn.");
    } finally { setBusy(false); }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!selected || !preview || !approved || busy) return;
    setBusy(true); setError(null);
    try {
      const result = await api.importChatGpt(selected, {
        title: title.trim(), world: { name: world.trim() }, persona: { name: persona.trim() },
        characters: cast.split(",").map((name) => name.trim()).filter(Boolean).map((name) =>
          ({ id: "", name, aliases: [] })),
      }, keyRef.current);
      const now = new Date().toISOString();
      onImported({ id: result.campaign_id, title: title.trim(), created_at: now, updated_at: now, archived_at: null });
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Không thể nhập thread. Dữ liệu gốc vẫn nằm trên thiết bị.");
    } finally { setBusy(false); }
  }

  return <section className="create-card" aria-labelledby="chatgpt-import-title">
    <div className="section-heading"><div><p className="eyebrow">LỊCH SỬ CỦA BẠN</p><h2 id="chatgpt-import-title">Nhập hội thoại ChatGPT</h2></div><button type="button" className="quiet-button touch-target" onClick={onCancel}>Đóng</button></div>
    <p>Giải nén tệp ChatGPT ZIP và chọn <code>conversations.json</code> (hoặc các JSON được đánh số). Toàn bộ tệp được đọc trên máy; chỉ thread mày chọn mới được gửi tới Playroom để xem trước và nhập. Không có lượt gọi AI ở bước này.</p>
    {error && <div role="alert" className="form-error">{error}</div>}
    {notice && <p role="status">{notice}</p>}
    <div className="campaign-form">
      <label htmlFor="chatgpt-files">Tệp xuất từ ChatGPT</label>
      <input id="chatgpt-files" type="file" accept=".json,.zip,application/json" multiple onChange={(event) => void loadFiles(event)} />
      {conversations.length > 0 && <>
        <label htmlFor="chatgpt-thread">Chọn chính xác cuộc hội thoại cần nhập</label>
        <select id="chatgpt-thread" value={selectedIndex} onChange={(event) => choose(Number(event.target.value))}>
          {conversations.map((item, index) => <option key={item.id} value={index}>{item.title || "(không có tiêu đề)"} — {item.id.slice(0, 8)}</option>)}
        </select>
        <button type="button" className="quiet-button touch-target" disabled={busy} onClick={() => void doPreview()}>Xem trước thread này</button>
      </>}
      {preview && selected && <form className="campaign-form" onSubmit={(event) => void submit(event)}>
        <p role="status">Tìm thấy <strong>{preview.turn_count}</strong> cặp người chơi / AI trong nhánh ChatGPT đang chọn. Bỏ qua <strong>{preview.skipped_messages}</strong> thông điệp không đủ điều kiện; không nhập nhánh AI thay thế.</p>
        {preview.warnings.map((warning) => <p key={warning} className="form-error">{warning}</p>)}
        <details><summary>Xem hai lượt đầu/cuối</summary>
          <p><strong>Người chơi (đầu):</strong> {preview.sample_first.action_text}</p><p><strong>AI (đầu):</strong> {preview.sample_first.narrative_text}</p>
          <p><strong>Người chơi (cuối):</strong> {preview.sample_last.action_text}</p><p><strong>AI (cuối):</strong> {preview.sample_last.narrative_text}</p>
        </details>
        <label htmlFor="import-campaign-title">Tên chiến dịch mới</label><input id="import-campaign-title" required maxLength={160} value={title} onChange={(event) => setTitle(event.target.value)} />
        <label htmlFor="import-world">Thế giới</label><input id="import-world" required value={world} onChange={(event) => setWorld(event.target.value)} />
        <label htmlFor="import-persona">Persona người chơi</label><input id="import-persona" required value={persona} onChange={(event) => setPersona(event.target.value)} />
        <label htmlFor="import-cast">Nhân vật đã xác nhận (cách nhau dấu phẩy)</label><input id="import-cast" value={cast} onChange={(event) => setCast(event.target.value)} placeholder="Yuna, Gi A, Yoongi" />
        <p>Import giữ nguyên lời người chơi và AI cũ; chưa tự tạo trí nhớ/canon, chưa tự xác định NPC nào đang có mặt. Kiểm tra Hồ sơ / Cảnh trước khi chơi tiếp, nhất là quy tắc không tự điều khiển Henn.</p>
        <label><input type="checkbox" checked={approved} onChange={(event) => setApproved(event.target.checked)} /> Tôi đã xem đúng thread, hiểu phần bị bỏ qua và muốn tạo chiến dịch mới.</label>
        <button className="primary-button touch-target" type="submit" disabled={!approved || busy}>{busy ? "Đang nhập…" : "Nhập và mở chiến dịch"}</button>
      </form>}
    </div>
  </section>;
}
