import { useEffect, useState } from "react";
import { api, ApiError } from "../api/client";
import type { ModelProfileSummary } from "../api/types";
import { useToast } from "./Toast";

export function CustomProviderForm({
  profile,
  onSaved,
}: {
  profile?: ModelProfileSummary;
  onSaved: (profile: ModelProfileSummary) => void;
}) {
  const toast = useToast();
  const [endpoint, setEndpoint] = useState("");
  const [model, setModel] = useState("");
  const [key, setKey] = useState("");
  const [credentialId, setCredentialId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const savedEndpoint = profile?.endpoint;
  useEffect(() => {
    if (profile) {
      setEndpoint(profile.endpoint ?? "");
      setModel(profile.model);
      setCredentialId(profile.secret_version ?? "");
    }
  }, [profile?.id, profile?.version]);
  function changeEndpoint(value: string) {
    if (savedEndpoint) {
      try {
        if (new URL(savedEndpoint).origin !== new URL(value).origin)
          setCredentialId("");
      } catch {
        /* incomplete input is validated by the server */
      }
    }
    setEndpoint(value);
  }
  async function save() {
    if (!endpoint.trim() || !model.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      let selected = credentialId || undefined;
      if (key.trim()) {
        selected = (await api.addCredential(key.trim())).id;
        setCredentialId(selected);
        setKey("");
      }
      const profile = await api.createCustomProfile({
        endpoint: endpoint.trim(),
        model: model.trim(),
        credential_id: selected,
      });
      onSaved(profile);
      toast.success("Đã lưu cấu hình custom provider.");
    } catch (cause) {
      const message =
        cause instanceof ApiError
          ? cause.message
          : "Không thể lưu custom provider.";
      setError(message);
      toast.error("Không thể lưu custom provider.");
    } finally {
      setBusy(false);
    }
  }
  return (
    <fieldset
      disabled={busy}
      aria-label="Custom OpenAI-compatible provider"
      className="custom-provider-form"
    >
      <legend>Custom OpenAI-compatible</legend>
      <p className="details-meta">
        Chỉ lưu URL và model ID; endpoint quản lý chi phí và quota.
      </p>
      <label htmlFor="custom-endpoint">Endpoint URL</label>
      <input
        className="touch-target"
        id="custom-endpoint"
        value={endpoint}
        onChange={(event) => changeEndpoint(event.target.value)}
        placeholder="http://127.0.0.1:1234/v1"
      />
      <label htmlFor="custom-model">Model ID</label>
      <input
        className="touch-target"
        id="custom-model"
        value={model}
        onChange={(event) => setModel(event.target.value)}
        placeholder="local-model"
      />
      <label htmlFor="custom-key">API key (optional)</label>
      <input
        className="touch-target"
        id="custom-key"
        type="password"
        autoComplete="off"
        value={key}
        onChange={(event) => setKey(event.target.value)}
        placeholder={
          credentialId
            ? "Đã lưu key; để trống để giữ key"
            : "Để trống nếu endpoint không cần key"
        }
      />
      {credentialId && (
        <button
          type="button"
          className="quiet-button touch-target"
          onClick={() => setCredentialId("")}
        >
          Bỏ key đã lưu
        </button>
      )}
      {error && (
        <p role="alert" className="form-error">
          {error}
        </p>
      )}
      <button
        type="button"
        className="primary-button touch-target"
        disabled={busy || !endpoint.trim() || !model.trim()}
        onClick={save}
      >
        {busy ? "Đang lưu…" : "Lưu custom provider"}
      </button>
    </fieldset>
  );
}
