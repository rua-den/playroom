import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

type Toast = { id: number; kind: "success" | "error"; message: string };
type ToastApi = { success: (message: string) => void; error: (message: string) => void };
const noop = () => undefined;
const ToastContext = createContext<ToastApi>({ success: noop, error: noop });

export function useToast() { return useContext(ToastContext); }

export function ToastProvider({ children, ownerKey }: { children: ReactNode; ownerKey?: string }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const nextId = useRef(0);
  const add = useCallback((kind: Toast["kind"], message: string) => {
    const id = ++nextId.current;
    setToasts((current) => [...current, { id, kind, message }].slice(-3));
  }, []);
  const remove = useCallback((id: number) => setToasts((current) => current.filter((toast) => toast.id !== id)), []);
  useEffect(() => { setToasts([]); }, [ownerKey]);
  const api = useMemo(() => ({ success: (message: string) => add("success", message), error: (message: string) => add("error", message) }), [add]);
  return <ToastContext.Provider value={api}>{children}{typeof document !== "undefined" && createPortal(<ToastViewport toasts={toasts} onDismiss={remove} />, document.body)}</ToastContext.Provider>;
}

function ToastViewport({ toasts, onDismiss }: { toasts: Toast[]; onDismiss: (id: number) => void }) {
  return <div className="toast-viewport" role="region" aria-label="Thông báo">{toasts.map((toast) => <ToastItem key={toast.id} toast={toast} onDismiss={onDismiss} />)}</div>;
}

function ToastItem({ toast, onDismiss }: { toast: Toast; onDismiss: (id: number) => void }) {
  const [paused, setPaused] = useState(false);
  useEffect(() => { if (toast.kind === "error" || paused) return; const timer = window.setTimeout(() => onDismiss(toast.id), 5000); return () => window.clearTimeout(timer); }, [onDismiss, paused, toast.id, toast.kind]);
  return <div className={`toast toast-${toast.kind}`} role={toast.kind === "success" ? "status" : "note"} aria-live={toast.kind === "success" ? "polite" : "off"} aria-atomic="true" onMouseEnter={() => setPaused(true)} onMouseLeave={() => setPaused(false)} onFocus={() => setPaused(true)} onBlur={() => setPaused(false)}>
    <span>{toast.message}</span><button type="button" className="toast-close touch-target" aria-label="Đóng thông báo" onClick={() => onDismiss(toast.id)}>Đóng</button>
  </div>;
}
