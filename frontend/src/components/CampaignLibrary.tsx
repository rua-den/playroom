import type { CampaignSummary } from "../api/types";

type Props = {
  campaigns: CampaignSummary[];
  trash: CampaignSummary[];
  mode: "active" | "trash";
  selectedId: string | null;
  error: string | null;
  onMode: (mode: "active" | "trash") => void;
  onCreate: () => void;
  onChoose: (id: string) => void;
  onDelete: (item: CampaignSummary) => void;
  onRestore: (item: CampaignSummary) => void;
  onImport: (mode: "chatgpt" | "legacy") => void;
  formatDate: (value: string) => string;
  ariaHidden?: boolean;
  restorePending?: Set<string>;
  trashLoading?: boolean;
};

export function CampaignLibrary({ campaigns, trash, mode, selectedId, error, onMode, onCreate, onChoose, onDelete, onRestore, onImport, formatDate, ariaHidden = false, restorePending = new Set(), trashLoading = false }: Props) {
  const items = mode === "trash" ? trash : (selectedId ? [campaigns.find((item) => item.id === selectedId), ...campaigns.filter((item) => item.id !== selectedId)].filter(Boolean) as CampaignSummary[] : campaigns);
  return <section className="story-library" aria-labelledby="library-title" aria-hidden={ariaHidden}>
    <div className="section-heading"><div><h1 id="library-title">{mode === "trash" ? "Thùng rác" : "Thư viện truyện"}</h1><p className="library-intro">{mode === "trash" ? "Truyện đã xoá vẫn có thể khôi phục." : campaigns.length ? "Mở lại một câu chuyện đã lưu hoặc bắt đầu một thế giới mới." : "Tạo truyện mới hoặc nhập một câu chuyện đã lưu."}</p></div>{mode === "active" && (!error || campaigns.length > 0) && <button type="button" className={selectedId ? "quiet-button touch-target" : "primary-button touch-target"} onClick={onCreate}>+ Tạo truyện mới</button>}</div>
    <div className="library-view-toggle" role="group" aria-label="Chế độ thư viện"><button type="button" className="quiet-button touch-target" aria-pressed={mode === "active"} onClick={() => onMode("active")}>Thư viện</button><button type="button" className="quiet-button touch-target" aria-pressed={mode === "trash"} onClick={() => onMode("trash")}>Thùng rác</button></div>
    {mode === "trash" && trashLoading && <div role="status">Đang tải Thùng rác…</div>}
    {mode === "active" && !campaigns.length && !error && <div className="library-empty"><svg viewBox="0 0 48 48" width="42" height="42" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M7 9c6-1.5 11-.2 17 3v27c-6-2.8-11-4-17-2.5z"/><path d="M41 9c-6-1.5-11-.2-17 3v27c6-2.8-11-4-17-2.5z"/><path d="M13 17h5M13 23h5M30 17h5M30 23h5"/></svg><div><h2>Chưa có truyện nào</h2><p>Bắt đầu truyện mới hoặc nhập hội thoại ChatGPT hay Legacy Bundle để tiếp tục.</p></div></div>}
    {mode === "trash" && !trashLoading && !trash.length && !error && <div className="library-empty"><div><h2>Thùng rác đang trống</h2><p>Truyện bạn xoá sẽ xuất hiện ở đây để khôi phục.</p></div></div>}
    {error && mode === "trash" && <div role="alert" className="form-error">{error}</div>}
    <div className="story-library-grid">{items.map((item) => { const pending = restorePending.has(item.id); return <article aria-label={item.title} className={`story-card ${item.id === selectedId && mode === "active" ? "is-current" : ""}`} key={item.id}><div><p className="story-card-status">{mode === "trash" ? "Trong thùng rác" : item.id === selectedId ? "Đang đọc" : item.archived_at ? "Đã lưu trữ" : "Đã lưu"}</p><h2>{item.title}</h2><p className="details-meta">{mode === "trash" ? `Đã xoá ${item.deleted_at ? formatDate(item.deleted_at) : ""}` : `Cập nhật ${formatDate(item.updated_at)}`}</p></div>{mode === "trash" ? <button type="button" className="quiet-button touch-target" aria-label={`${pending ? "Đang khôi phục" : "Khôi phục"}: ${item.title}`} disabled={pending} onClick={() => onRestore(item)}>{pending ? "Đang khôi phục…" : "Khôi phục"}</button> : <div className="story-card-actions"><button type="button" className={item.id === selectedId ? "primary-button touch-target" : "quiet-button touch-target"} onClick={() => onChoose(item.id)}>{item.id === selectedId ? "Đọc tiếp" : "Mở truyện"}</button><button type="button" className="quiet-button touch-target story-delete" aria-label={`Xoá truyện: ${item.title}`} onClick={() => onDelete(item)}>Xoá</button></div>}</article>; })}</div>
    {mode === "active" && (!error || campaigns.length > 0) && <div className="library-import-actions"><button type="button" className="quiet-button touch-target" onClick={() => onImport("chatgpt")}>Nhập hội thoại ChatGPT</button><button type="button" className="quiet-button touch-target" onClick={() => onImport("legacy")}>Nhập Legacy Bundle</button></div>}
  </section>;
}
