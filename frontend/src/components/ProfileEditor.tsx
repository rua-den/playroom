import { useState } from "react";
import { api, ApiError } from "../api/client";
import { useToast } from "./Toast";

type Profile = { kind: string; data: Record<string, unknown> };
interface Props { campaignId: string; branchId: string; stateVersion: number; profiles: Record<string, Profile>; onSaved?: (result: { state_version: number; checkpoint_id: string }) => void; onConflict?: () => void; }

const pretty = (value: unknown) => typeof value === "string" ? value : Array.isArray(value) ? value.join(", ") : "";

function GuidanceField({ id, label, value, onChange }: { id: string; label: string; value: unknown; onChange: (value: unknown) => void }) {
  const isList = Array.isArray(value) && value.every((item) => typeof item === "string");
  if (value != null && typeof value !== "string" && !isList) {
    return <p>{label} có dữ liệu có cấu trúc; dữ liệu này được giữ nguyên khi lưu hồ sơ.</p>;
  }
  return <>
    <label htmlFor={id}>{label}</label>
    {isList && <p id={`${id}-help`}>Mỗi dòng một mục.</p>}
    <textarea id={id} aria-describedby={isList ? `${id}-help` : undefined} rows={3}
      value={isList ? (value as string[]).join("\n") : typeof value === "string" ? value : ""}
      onChange={(event) => onChange(isList ? event.target.value.split("\n") : event.target.value)} />
  </>;
}

export function ProfileEditor({ campaignId, branchId, stateVersion, profiles, onSaved, onConflict }: Props) {
  const toast = useToast();
  const [drafts, setDrafts] = useState(() => Object.fromEntries(Object.entries(profiles).map(([key, profile]) => [key, { ...profile.data, aliases: Array.isArray(profile.data.aliases) ? profile.data.aliases.join(", ") : pretty(profile.data.aliases) }])) as Record<string, Record<string, unknown>>);
  const [error, setError] = useState<string | null>(null);
  const update = (key: string, field: string, value: unknown) => setDrafts((current) => ({ ...current, [key]: { ...current[key], [field]: value } }));
  async function save(key: string) {
    const data = { ...drafts[key] };
    if (typeof data.aliases === "string") data.aliases = data.aliases.split(",").map((item) => item.trim()).filter(Boolean);
    try { const result = await api.updateProfile(campaignId, key, { branch_id: branchId, expected_state_version: stateVersion, data }); onSaved?.(result); setError(null); toast.success("Đã lưu hồ sơ."); }
    catch (cause) { if (cause instanceof ApiError && cause.status === 409) { onConflict?.(); setError("Phiên bản đã thay đổi; bản nháp vẫn được giữ lại."); } else setError("Không thể lưu hồ sơ."); toast.error("Không thể lưu hồ sơ."); }
  }
  async function addCharacter() { const id = crypto.randomUUID(); const data = { id, name: "Nhân vật mới", aliases: [] }; try { const result = await api.addCharacter(campaignId, { branch_id: branchId, expected_state_version: stateVersion, character: data }); setDrafts((current) => ({ ...current, [`character:${id}`]: data })); onSaved?.(result); setError(null); toast.success("Đã thêm nhân vật."); } catch (cause) { if (cause instanceof ApiError && cause.status === 409) onConflict?.(); setError("Không thể thêm nhân vật."); toast.error("Không thể thêm nhân vật."); } }
  async function removeCharacter(key: string) { try { const result = await api.removeProfile(campaignId, key, branchId, stateVersion); setDrafts((current) => { const next = { ...current }; delete next[key]; return next; }); onSaved?.(result); setError(null); toast.success("Đã xóa nhân vật."); } catch (cause) { if (cause instanceof ApiError && cause.status === 409) onConflict?.(); setError("Không thể xóa nhân vật."); toast.error("Không thể xóa nhân vật."); } }
  return <section aria-label="Chỉnh sửa hồ sơ" className="editor-stack">{error && <div role="alert" className="form-error">{error}</div>}{Object.entries(drafts).map(([key, data]) => { const label = key.startsWith("character:") ? `nhân vật ${String(data.name ?? key)}` : key === "world" ? "thế giới" : key === "persona" ? "persona" : key; const nameId = `profile-${key}-name`; return <fieldset key={key}><legend>{label}</legend>{key === "style" ? <><label htmlFor="style-language">Ngôn ngữ style</label><select id="style-language" value={pretty(data.language) || "vi"} onChange={(event) => update(key, "language", event.target.value)}><option value="vi">Tiếng Việt</option><option value="en">English</option></select><label htmlFor="style-length">Độ dài style</label><select id="style-length" value={pretty(data.length) || "medium"} onChange={(event) => update(key, "length", event.target.value)}><option value="short">Ngắn</option><option value="medium">Vừa</option><option value="long">Dài</option></select><label htmlFor="style-headings">Tiêu đề style</label><select id="style-headings" value={pretty(data.heading_level) || "low"} onChange={(event) => update(key, "heading_level", event.target.value)}><option value="none">Không có</option><option value="low">Ít</option><option value="medium">Vừa</option></select><label htmlFor="style-emojis">Emoji style</label><select id="style-emojis" value={pretty(data.emoji_level) || "low"} onChange={(event) => update(key, "emoji_level", event.target.value)}><option value="none">Không có</option><option value="low">Ít</option><option value="medium">Vừa</option></select><label htmlFor="style-viewpoint">Ngôi kể style</label><select id="style-viewpoint" value={pretty(data.viewpoint) || "third_person"} onChange={(event) => update(key, "viewpoint", event.target.value)}><option value="third_person">Ngôi thứ ba</option><option value="first_person">Ngôi thứ nhất</option></select><GuidanceField id="style-custom" label="Hướng dẫn phong cách riêng" value={data.custom} onChange={(value) => update(key, "custom", value)} /><label htmlFor="style-agency">Quy tắc agency</label><output id="style-agency">{pretty(data.agency_rule) || "Player agency forbids invented speech/thought/choices."}</output></> : <><label htmlFor={nameId}>Tên {label}</label><input id={nameId} value={pretty(data.name)} onChange={(event) => update(key, "name", event.target.value)} /><label htmlFor={`profile-${key}-description`}>Mô tả {label}</label><textarea id={`profile-${key}-description`} value={pretty(data.description)} onChange={(event) => update(key, "description", event.target.value)} />{(key.startsWith("character:") || key === "persona") && <>{[["voice", "Giọng nói"], ["traits", "Tính cách"], ["knowledge", "Kiến thức"]].map(([field, title]) => <GuidanceField key={field} id={`profile-${key}-${field}`} label={`${title} ${label}`} value={data[field] ?? (field === "traits" ? [] : "")} onChange={(value) => update(key, field, value)} />)}</>}{key.startsWith("character:") && <><label htmlFor={`profile-${key}-aliases`}>Bí danh {String(data.name ?? "")}</label><input id={`profile-${key}-aliases`} value={pretty(data.aliases)} onChange={(event) => update(key, "aliases", event.target.value)} /><button type="button" className="quiet-button touch-target" onClick={() => removeCharacter(key)}>Xóa {label}</button></>}</>}<button type="button" className="primary-button touch-target" onClick={() => save(key)}>Lưu {label}</button></fieldset>; })}<button type="button" className="quiet-button touch-target" onClick={addCharacter}>Thêm nhân vật</button></section>;
}
