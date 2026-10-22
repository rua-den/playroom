import { ReactNode, useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";

interface ModalProps {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
  closeLabel?: string;
  size?: "standard" | "wide";
}

const FOCUSABLE = ["button:not([disabled])", "[href]", "input:not([disabled])", "textarea:not([disabled])", "select:not([disabled])", "summary", "[tabindex]:not([tabindex='-1'])"].join(",");

let activePortals: HTMLElement[] = [];
let savedOverflow: string | null = null;
const savedInert = new Map<HTMLElement, { property: boolean; attribute: boolean }>();
const modalStackListeners = new Set<() => void>();

export function subscribeModalStack(listener: () => void) {
  modalStackListeners.add(listener);
  listener();
  return () => modalStackListeners.delete(listener);
}

export function getActiveModalToastOutlet() {
  return activePortals[activePortals.length - 1]?.querySelector<HTMLElement>(".modal-toast-outlet") ?? null;
}

function notifyModalStack() { modalStackListeners.forEach((listener) => listener()); }

function setInert(node: HTMLElement, inert: boolean) {
  node.inert = inert;
  if (inert) node.setAttribute("inert", "");
  else node.removeAttribute("inert");
}

function syncModalEnvironment() {
  const activePortal = activePortals[activePortals.length - 1] ?? null;
  if (!activePortals.length) {
    savedInert.forEach(({ property, attribute }, node) => {
      if (!node.isConnected) return;
      node.inert = property;
      if (attribute) node.setAttribute("inert", "");
      else node.removeAttribute("inert");
    });
    savedInert.clear();
    if (savedOverflow !== null) document.body.style.overflow = savedOverflow;
    savedOverflow = null;
    return;
  }

  if (savedOverflow === null) savedOverflow = document.body.style.overflow;
  document.body.style.overflow = "hidden";
  Array.from(document.body.children).forEach((child) => {
    const node = child as HTMLElement;
    if (!savedInert.has(node)) savedInert.set(node, { property: node.inert, attribute: node.hasAttribute("inert") });
    const isToast = node.classList.contains("toast-viewport") || node.classList.contains("toast-portal-host");
    setInert(node, node !== activePortal && !isToast);
  });
}

export function Modal({ open, title, onClose, children, closeLabel = "Đóng", size = "standard" }: ModalProps) {
  const titleId = useId();
  const [hasOpened, setHasOpened] = useState(open);
  const rootRef = useRef<HTMLDivElement>(null);
  const dialogRef = useRef<HTMLElement>(null);
  const priorFocus = useRef<HTMLElement | null>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => { if (open) setHasOpened(true); }, [open]);

  useEffect(() => {
    if (!open) return;
    const portal = rootRef.current;
    const dialog = dialogRef.current;
    if (!portal || !dialog) return;
    const dialogElement = dialog;

    priorFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    activePortals = activePortals.filter((item) => item !== portal);
    activePortals.push(portal);
    syncModalEnvironment();
    notifyModalStack();

    const close = dialogElement.querySelector<HTMLElement>("[data-modal-close]");
    (close ?? dialogElement.querySelector<HTMLElement>(FOCUSABLE) ?? dialogElement).focus();

    const focusable = () => Array.from(dialogElement.querySelectorAll<HTMLElement>(FOCUSABLE))
      .filter((element) => {
        if (element.matches(":disabled, input[type=hidden]") || element.tabIndex < 0 || element.getAttribute("aria-disabled") === "true" || element.closest("[hidden], [aria-hidden='true'], [aria-disabled='true'], [inert]")) return false;
        const closedDetails = element.closest("details:not([open])");
        if (closedDetails && !element.closest("summary")) return false;
        for (let node: HTMLElement | null = element; node && dialogElement.contains(node); node = node.parentElement) {
          const style = window.getComputedStyle(node);
          if (style.display === "none" || style.visibility === "hidden" || style.visibility === "collapse") return false;
        }
        return true;
      });
    function onKeyDown(event: KeyboardEvent) {
      if (activePortals[activePortals.length - 1] !== portal) return;
      if (event.key === "Escape") {
        event.preventDefault();
        onCloseRef.current();
        return;
      }
      if (event.key !== "Tab" || !dialogElement.contains(document.activeElement)) return;
      const targets = focusable();
      if (!targets.length) { event.preventDefault(); dialogElement.focus(); return; }
      const current = targets.indexOf(document.activeElement as HTMLElement);
      const next = event.shiftKey
        ? current <= 0 ? targets.length - 1 : current - 1
        : current < 0 || current === targets.length - 1 ? 0 : current + 1;
      event.preventDefault();
      targets[next].focus();
    }
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      activePortals = activePortals.filter((item) => item !== portal);
      syncModalEnvironment();
      notifyModalStack();
      const target = priorFocus.current;
      priorFocus.current = null;
      if (target?.isConnected && !target.closest("[inert]")) target.focus();
    };
  }, [open]);

  return createPortal(
    <div className="app-modal-portal" data-modal-root ref={rootRef} hidden={!open}>
      <div className="app-modal-backdrop mobile-overlay" hidden={!open}>
        <section className={`app-modal app-modal-${size}`} role="dialog" aria-modal={open} aria-labelledby={titleId} tabIndex={-1} ref={dialogRef}>
          <header className="app-modal-header">
            <h2 id={titleId}>{title}</h2>
            <button type="button" className="quiet-button touch-target" data-modal-close onClick={onClose} aria-label={closeLabel}><span aria-hidden="true">Đóng</span></button>
          </header>
          <div className="modal-toast-outlet" />
          <div className="app-modal-body">{(open || hasOpened) && children}</div>
        </section>
      </div>
    </div>,
    document.body,
  );
}
