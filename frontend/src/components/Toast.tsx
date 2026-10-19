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
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);
  const remainingMs = useRef(5000);
  const startedAt = useRef<number | null>(null);
  const paused = hovered || focused;
  useEffect(() => {
    if (toast.kind === "error" || paused || remainingMs.current <= 0) return;
    startedAt.current = performance.now();
    const timer = window.setTimeout(() => {
      remainingMs.current = 0;
      startedAt.current = null;
      onDismiss(toast.id);
    }, remainingMs.current);
    return () => {
      window.clearTimeout(timer);
      if (startedAt.current !== null) {
        remainingMs.current = Math.max(0, remainingMs.current - (performance.now() - startedAt.current));
        startedAt.current = null;
      }
    };
  }, [onDismiss, paused, toast.id, toast.kind]);
  return <div className={`toast toast-${toast.kind}`} role={toast.kind === "success" ? "status" : "note"} aria-live={toast.kind === "success" ? "polite" : "off"} aria-atomic="true" onMouseEnter={() => setHovered(true)} onMouseLeave={() => setHovered(false)} onFocus={() => setFocused(true)} onBlur={(event) => { if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setFocused(false); }}>
    <span>{toast.message}</span><button type="button" className="toast-close touch-target" aria-label="Đóng thông báo" onClick={() => onDismiss(toast.id)}>Đóng</button>
  </div>;
}
