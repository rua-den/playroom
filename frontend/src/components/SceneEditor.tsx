import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { SceneState } from "../api/types";
import { useToast } from "./Toast";

interface Props { campaignId: string; branchId: string; stateVersion: number; characters?: Array<{ id: string; name: string }>; onSaved?: (result: { state_version: number; checkpoint_id: string }) => void; onConflict?: () => void; }
export function SceneEditor({ campaignId, branchId, stateVersion, characters = [], onSaved, onConflict }: Props) {
  const toast = useToast();
  const [scene, setScene] = useState<SceneState>({ focus_scene_id: null, scenes: [] }); const [error, setError] = useState<string | null>(null);
  const [loadAttempt, setLoadAttempt] = useState(0);
  const [loadedBranch, setLoadedBranch] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const branchKey = JSON.stringify([campaignId, branchId]);
  const ready = loadedBranch === branchKey;
  useEffect(() => {
    let active = true;
    setLoading(true);
    setLoadedBranch(null);
    setError(null);
    api.getScene(campaignId, branchId).then((next) => {
      if (!active) return;
      setScene({ focus_scene_id: next.focus_scene_id, scenes: Object.values(next.scenes ?? {}) });
      setLoadedBranch(branchKey);
    }).catch(() => {
      if (active) setError("Không thể tải bản đồ cảnh.");
    }).finally(() => {
      if (active) setLoading(false);
    });
    return () => { active = false; };
  }, [campaignId, branchId, branchKey, loadAttempt]);
  async function save() {
    if (!ready || saving) return;
    setSaving(true);
    try {
      const result = await api.updateScene(campaignId, { branch_id: branchId, expected_state_version: stateVersion, scene_state: scene });
      onSaved?.(result); setError(null); toast.success("Đã lưu cảnh.");
    } catch {
      onConflict?.(); setError("Không thể lưu cảnh; bản nháp vẫn được giữ lại."); toast.error("Không thể lưu cảnh.");
    } finally { setSaving(false); }
  }
  function addScene() { const id = crypto.randomUUID(); setScene((current) => ({ ...current, scenes: [...current.scenes, { id, name: "", present_ids: [] }], focus_scene_id: current.focus_scene_id ?? id })); }
  function removeScene(id: string) { setScene((current) => { const scenes = current.scenes.filter((item) => item.id !== id); return { scenes, focus_scene_id: current.focus_scene_id === id ? (scenes[0]?.id ?? null) : current.focus_scene_id }; }); }
  function togglePresence(sceneId: string, characterId: string, present: boolean) { setScene((current) => ({ ...current, scenes: current.scenes.map((item) => item.id === sceneId ? { ...item, present_ids: present ? [...item.present_ids, characterId] : item.present_ids.filter((id) => id !== characterId) } : item) })); }
  return <section aria-label="Chỉnh sửa cảnh" className="editor-stack">{error && <div role="alert" className="form-error">{error}</div>}{loading && <p aria-live="polite">Đang tải bản đồ cảnh…</p>}{!loading && !ready && <button type="button" className="quiet-button touch-target" onClick={() => setLoadAttempt((attempt) => attempt + 1)}>Thử tải lại cảnh</button>}{ready && !scene.scenes.length && <div className="editor-empty"><h2>Chưa có cảnh nào</h2><p>Thêm cảnh để chọn nơi đang diễn ra và đánh dấu nhân vật có mặt.</p></div>}<button type="button" className="quiet-button touch-target" disabled={!ready || saving} onClick={addScene}>Thêm cảnh</button>{ready && scene.scenes.map((item, index) => <fieldset disabled={saving} key={item.id}><legend>Cảnh {index + 1}</legend><label htmlFor={`scene-${item.id}`}>Tên cảnh {index + 1}</label><input id={`scene-${item.id}`} value={String(item.name ?? "")} onChange={(event) => setScene((current) => ({ ...current, scenes: current.scenes.map((sceneItem) => sceneItem.id === item.id ? { ...sceneItem, name: event.target.value } : sceneItem) }))} /><label htmlFor={`scene-focus-${item.id}`}><input id={`scene-focus-${item.id}`} type="radio" name="focus-scene" checked={scene.focus_scene_id === item.id} onChange={() => setScene((current) => ({ ...current, focus_scene_id: item.id }))} />Cảnh hiện tại</label>{characters.map((character) => <label key={character.id}><input type="checkbox" checked={item.present_ids.includes(character.id)} onChange={(event) => togglePresence(item.id, character.id, event.target.checked)} />{character.name} có mặt ở cảnh {index + 1}</label>)}<button type="button" className="quiet-button touch-target" onClick={() => removeScene(item.id)}>Xóa cảnh {index + 1}</button></fieldset>)}<button type="button" className="primary-button touch-target" disabled={!ready || saving} onClick={save}>Lưu cảnh</button></section>;
}
