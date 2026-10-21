import { ChangeEvent, FormEvent, useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api/client";
import { ChatGptConversation } from "../features/import/parseChatGptExport";
import { readChatGptExportFiles } from "../features/import/readChatGptExportFiles";

type Preview = Awaited<ReturnType<typeof api.previewChatGptImport>>;
const MAX_INPUT_BYTES = 20 * 1024 * 1024;
interface Props {
  onImported: (campaign: { id: string; title: string; created_at: string; updated_at: string; archived_at: null }) => void;
  onCancel: () => void;
}

function makeKey() { return globalThis.crypto.randomUUID(); }

export function ChatGptImport({ onImported, onCancel }: Props) {
  const [conversations, setConversations] = useState<ChatGptConversation[]>([]);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [title, setTitle] = useState("");
  const [world, setWorld] = useState("");
  const [persona, setPersona] = useState("");
  const [cast, setCast] = useState("");
  const [approved, setApproved] = useState(false);
  const [busy, setBusy] = useState(false);
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const keyRef = useRef(makeKey());
  const sourceEpochRef = useRef(0);
  const mountedRef = useRef(true);
  const importInFlightRef = useRef(false);
  const selected = conversations[selectedIndex];

  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  async function loadFiles(event: ChangeEvent<HTMLInputElement>) {
    const epoch = ++sourceEpochRef.current;
    setConversations([]); setSelectedIndex(0); setPreview(null); setError(null); setNotice(null); setApproved(false); setBusy(false);
    keyRef.current = makeKey();
    const files = Array.from(event.target.files ?? []);
    if (!files.length) return;
    if (files.reduce((total, file) => total + file.size, 0) > MAX_INPUT_BYTES) {
      setError("Tổng tệp đầu vào vượt quá giới hạn 20 MiB.");
      return;
    }
    try {
      const found = await readChatGptExportFiles(files);
      if (!mountedRef.current || sourceEpochRef.current !== epoch) return;
      setConversations(found); setSelectedIndex(0);
      setTitle(found[0]?.title.slice(0, 160) || "Truyện nhập từ ChatGPT");
      setNotice(`Đã đọc ${found.length} cuộc hội thoại trên thiết bị. Chưa tải nội dung lên server.`);
    } catch (cause) {
      if (!mountedRef.current || sourceEpochRef.current !== epoch) return;
      setConversations([]);
      setError(cause instanceof Error ? cause.message : "Không thể đọc tệp export.");
    }
  }

  function choose(index: number) {
    ++sourceEpochRef.current;
    setSelectedIndex(index); setPreview(null); setApproved(false); setError(null); setNotice(null); setBusy(false);
    setTitle(conversations[index]?.title.slice(0, 160) ?? "");
    keyRef.current = makeKey();
  }

  async function doPreview() {
    if (!selected) return;
    const epoch = sourceEpochRef.current;
    const conversation = selected;
    const conversationBytes = new TextEncoder().encode(JSON.stringify(conversation)).byteLength;
    if (conversationBytes > MAX_INPUT_BYTES) {
      setPreview(null); setError("Thread đã chọn vượt quá giới hạn 20 MiB.");
      return;
    }
    setBusy(true); setError(null);
    try {
      const result = await api.previewChatGptImport(conversation);
      if (!mountedRef.current || sourceEpochRef.current !== epoch) return;
      setPreview(result); setNotice(null);
    } catch (cause) {
      if (!mountedRef.current || sourceEpochRef.current !== epoch) return;
      setPreview(null);
      setError(cause instanceof ApiError ? cause.message : "Không thể xem trước thread đã chọn.");
    } finally {
      if (mountedRef.current && sourceEpochRef.current === epoch) setBusy(false);
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!selected || !preview || !approved || busy || importInFlightRef.current) {
      if (importInFlightRef.current) setError("Đang nhập thread này.");
      return;
    }
    const epoch = sourceEpochRef.current;
    const conversation = selected;
    const submittedTitle = title.trim();
    const submittedConfig = {
      title: submittedTitle,
      world: { name: world.trim() },
      persona: { name: persona.trim() },
      characters: cast.split(",").map((name) => name.trim()).filter(Boolean).map((name) => ({ id: "", name, aliases: [] })),
    };
    const importKey = keyRef.current;
    importInFlightRef.current = true;
    setImporting(true); setBusy(true); setError(null); setNotice("Bắt đầu nhập lịch sử theo từng phần an toàn…");
    try {
      let previousProgress = -1;
      let result: Awaited<ReturnType<typeof api.importChatGpt>>;
      while (true) {
        result = await api.importChatGpt(conversation, submittedConfig, importKey);
        if (!mountedRef.current || sourceEpochRef.current !== epoch) return;
        if (result.complete) break;
        if (result.imported_turns <= previousProgress || result.imported_turns >= result.turn_count) {
          throw new Error("Import progress did not advance");
        }
        previousProgress = result.imported_turns;
        setNotice(`Đã lưu ${result.imported_turns}/${result.turn_count} lượt. Có thể tiếp tục an toàn nếu cần tải lại.`);
      }
      const now = new Date().toISOString();
      setNotice(`Đã nhập đủ ${result.imported_turns}/${result.turn_count} lượt. Mở chiến dịch để duyệt checkpoint.`);
      onImported({ id: result.campaign_id, title: submittedTitle, created_at: now, updated_at: now, archived_at: null });
    } catch (cause) {
      if (mountedRef.current && sourceEpochRef.current === epoch) {
        setError(cause instanceof ApiError ? cause.message : "Không thể nhập thread. Tiến độ đã lưu có thể tiếp tục khi thử lại cùng thread.");
      }
    } finally {
      importInFlightRef.current = false;
      if (mountedRef.current) { setImporting(false); setBusy(false); }
    }
  }

  return <section className="create-card" aria-labelledby="chatgpt-import-title">
    <div className="section-heading"><div><p className="eyebrow">LỊCH SỬ CỦA BẠN</p><h2 id="chatgpt-import-title">Nhập hội thoại ChatGPT</h2></div><button type="button" className="quiet-button touch-target" onClick={onCancel}>Đóng</button></div>
    <p>Đọc ZIP và JSON trên thiết bị; tổng tệp đầu vào và thread được chọn mỗi loại tối đa 20 MiB. Nếu lớn hơn, hãy tách riêng thread hoặc tệp trước khi nhập. Chỉ thread bạn chọn mới được gửi tới Playroom để xem trước và nhập. Không có lượt gọi AI ở bước này.</p>
    {error && <div role="alert" className="form-error">{error}</div>}
    {notice && <p role="status">{notice}</p>}
    <div className="campaign-form">
      <label htmlFor="chatgpt-files">Tệp xuất từ ChatGPT</label>
      <input id="chatgpt-files" type="file" accept=".json,.zip,application/json,application/zip" multiple disabled={importing} onChange={(event) => void loadFiles(event)} />
      {conversations.length > 0 && <>
        <label htmlFor="chatgpt-thread">Chọn chính xác cuộc hội thoại cần nhập</label>
        <select id="chatgpt-thread" value={selectedIndex} disabled={importing} onChange={(event) => choose(Number(event.target.value))}>
          {conversations.map((item, index) => <option key={item.id} value={index}>{item.title || "(không có tiêu đề)"} — {item.id.slice(0, 8)}</option>)}
        </select>
        <button type="button" className="quiet-button touch-target" disabled={busy || importing} onClick={() => void doPreview()}>Xem trước thread này</button>
      </>}
      {preview && selected && <form className="campaign-form" onSubmit={(event) => void submit(event)}>
        <p role="status">Tìm thấy <strong>{preview.turn_count}</strong> cặp người chơi / AI trong nhánh ChatGPT đang chọn. Bỏ qua <strong>{preview.skipped_messages}</strong> thông điệp không đủ điều kiện; không nhập nhánh AI thay thế.</p>
        {preview.warnings.map((warning) => <p key={warning} className="form-error">{warning}</p>)}
        <details><summary>Xem hai lượt đầu/cuối</summary><p><strong>Người chơi (đầu):</strong> {preview.sample_first.action_text}</p><p><strong>AI (đầu):</strong> {preview.sample_first.narrative_text}</p><p><strong>Người chơi (cuối):</strong> {preview.sample_last.action_text}</p><p><strong>AI (cuối):</strong> {preview.sample_last.narrative_text}</p></details>
        <label htmlFor="import-campaign-title">Tên chiến dịch mới</label><input id="import-campaign-title" required maxLength={160} value={title} onChange={(event) => setTitle(event.target.value)} />
        <label htmlFor="import-world">Thế giới</label><input id="import-world" required value={world} onChange={(event) => setWorld(event.target.value)} />
        <label htmlFor="import-persona">Persona người chơi</label><input id="import-persona" required value={persona} onChange={(event) => setPersona(event.target.value)} />
        <label htmlFor="import-cast">Nhân vật đã xác nhận (cách nhau dấu phẩy)</label><input id="import-cast" value={cast} onChange={(event) => setCast(event.target.value)} placeholder="Tên nhân vật, tên nhân vật khác" />
        <p>Import giữ nguyên lời người chơi và AI cũ; chưa tự tạo trí nhớ/canon, chưa tự xác định NPC nào đang có mặt. Kiểm tra Hồ sơ / Cảnh trước khi chơi tiếp, nhất là quy tắc không tự điều khiển nhân vật của người chơi.</p>
        <label><input type="checkbox" checked={approved} onChange={(event) => setApproved(event.target.checked)} /> Tôi đã xem đúng thread, hiểu phần bị bỏ qua và muốn tạo chiến dịch tạm khóa để duyệt riêng.</label>
        <button className="primary-button touch-target" type="submit" disabled={!approved || busy || importing}>{busy ? "Đang nhập…" : "Nhập và mở chiến dịch"}</button>
      </form>}
    </div>
  </section>;
}
