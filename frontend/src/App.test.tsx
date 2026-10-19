import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "./App";
import { api, privateCache } from "./api/client";
import { generationIdentityKey } from "./components/GenerationComposer";

afterEach(() => {
  vi.restoreAllMocks();
  privateCache.clear();
});

describe("authentication shell", () => {
  it("shows a typed login error when credentials are rejected", async () => {
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce(new Response(null, { status: 401 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: "Invalid email or password" }), { status: 401, headers: { "content-type": "application/json" } })));
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole("heading", { name: "Đăng nhập Playroom" });
    await user.type(screen.getByLabelText("Email"), "owner@example.test");
    await user.type(screen.getByLabelText("Mật khẩu"), "wrong-password");
    await user.click(screen.getByRole("button", { name: "Đăng nhập" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Email hoặc mật khẩu không đúng.");
  });

  it("clears all private client cache when logging out", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "owner-1", email: "owner@example.test" }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);
    privateCache.set("stories", [{ id: "story-1" }]);
    privateCache.set("jobs:story-1", { id: "job-1" });
    privateCache.set("pending-key:story-1", "secretless-idempotency");
    localStorage.setItem(generationIdentityKey("owner-1", "campaign-1", "branch-1"), JSON.stringify({ idempotencyKey: "generation-key" }));
    const user = userEvent.setup();
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Thư viện truyện" }))
      .toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Đăng xuất" }));
    expect(await screen.findByRole("heading", { name: "Đăng nhập Playroom" })).toBeInTheDocument();
    expect(privateCache.size).toBe(0);
    expect(localStorage.getItem(generationIdentityKey("owner-1", "campaign-1", "branch-1"))).toBeNull();
    expect(fetchMock).toHaveBeenLastCalledWith("/api/auth/logout", expect.objectContaining({ method: "POST", credentials: "same-origin" }));
  });

  it("clears private cache and exits the shell when server logout is offline", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "owner-1", email: "owner@example.test" }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }))
      .mockRejectedValueOnce(new TypeError("Failed to fetch"));
    vi.stubGlobal("fetch", fetchMock);
    privateCache.set("stories", [{ id: "story-1" }]);
    localStorage.setItem(generationIdentityKey("owner-1", "campaign-1", "branch-1"), JSON.stringify({ idempotencyKey: "generation-key" }));
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole("heading", { name: "Thư viện truyện" });
    await user.click(screen.getByRole("button", { name: "Đăng xuất" }));
    expect(await screen.findByRole("heading", { name: "Đăng nhập Playroom" })).toBeInTheDocument();
    expect(privateCache.size).toBe(0);
    expect(localStorage.getItem(generationIdentityKey("owner-1", "campaign-1", "branch-1"))).toBeNull();
    expect(screen.getByRole("alert")).toHaveTextContent("chưa xác nhận được đăng xuất trên máy chủ");
  });

  it("clears private state and returns to login when an authenticated request expires", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "owner-1", email: "owner@example.test" }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: "Owner session is required" }), { status: 401 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ owner: { id: "owner-1", email: "owner@example.test" } }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    privateCache.set("stories", [{ id: "story-1" }]);
    localStorage.setItem(generationIdentityKey("owner-1", "campaign-1", "branch-1"), JSON.stringify({ idempotencyKey: "generation-key" }));
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole("heading", { name: "Thư viện truyện" });
    await expect(api.me()).rejects.toMatchObject({ status: 401 });
    expect(await screen.findByRole("heading", { name: "Đăng nhập Playroom" })).toBeInTheDocument();
    expect(privateCache.size).toBe(0);
    expect(localStorage.getItem(generationIdentityKey("owner-1", "campaign-1", "branch-1"))).toBeNull();
    expect(screen.getByRole("alert")).toHaveTextContent("Phiên đăng nhập đã hết hạn");
    await user.type(screen.getByLabelText("Email"), "owner@example.test");
    await user.type(screen.getByLabelText("Mật khẩu"), "correct-password");
    await user.click(screen.getByRole("button", { name: "Đăng nhập" }));
    expect(await screen.findByRole("heading", { name: "Thư viện truyện" })).toBeInTheDocument();
    expect(screen.queryByText("Phiên đăng nhập đã hết hạn")).not.toBeInTheDocument();
  });

  it("shows the login form immediately while a server logout is still pending", async () => {
    const never = new Promise<Response>(() => undefined);
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "owner-1", email: "owner@example.test" }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }))
      .mockReturnValueOnce(never);
    vi.stubGlobal("fetch", fetchMock);
    privateCache.set("stories", [{ id: "story-1" }]);
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole("heading", { name: "Thư viện truyện" });
    await user.click(screen.getByRole("button", { name: "Đăng xuất" }));
    expect(screen.getByRole("heading", { name: "Đăng nhập Playroom" })).toBeInTheDocument();
    expect(privateCache.size).toBe(0);
  });

  it("ignores an old protected 401 after logout and a successful re-login", async () => {
    let resolveProtected!: (response: Response) => void;
    let resolveLogout!: (response: Response) => void;
    const protectedRequest = new Promise<Response>((resolve) => { resolveProtected = resolve; });
    const logoutRequest = new Promise<Response>((resolve) => { resolveLogout = resolve; });
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "owner-1", email: "old@example.test" }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }))
      .mockReturnValueOnce(protectedRequest)
      .mockReturnValueOnce(logoutRequest)
      .mockResolvedValueOnce(new Response(JSON.stringify({ owner: { id: "owner-2", email: "new@example.test" } }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole("heading", { name: "Thư viện truyện" });
    const oldProtected = api.me();
    await user.click(screen.getByRole("button", { name: "Đăng xuất" }));
    await user.type(screen.getByLabelText("Email"), "new@example.test");
    await user.type(screen.getByLabelText("Mật khẩu"), "new-password");
    await user.click(screen.getByRole("button", { name: "Đăng nhập" }));
    await screen.findByRole("heading", { name: "Thư viện truyện" });
    privateCache.set("new-session", { owner: "owner-2" });
    resolveProtected(new Response(JSON.stringify({ detail: "expired" }), { status: 401 }));
    resolveLogout(new Response(null, { status: 204 }));
    await expect(oldProtected).rejects.toMatchObject({ status: 401 });
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(screen.getByText("new@example.test")).toBeInTheDocument();
    expect(privateCache.has("new-session")).toBe(true);
    expect(screen.queryByText("Phiên đăng nhập đã hết hạn")).not.toBeInTheDocument();
  });

  it("does not let a stale logout completion clear a re-login cache or notice", async () => {
    let resolveLogout!: (response: Response) => void;
    let logoutSignal: AbortSignal | undefined;
    let loginSawAbortedLogout = false;
    const logoutRequest = new Promise<Response>((resolve) => { resolveLogout = resolve; });
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "owner-1", email: "old@example.test" }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }))
      .mockImplementationOnce((_input, init) => {
        logoutSignal = init?.signal as AbortSignal | undefined;
        return logoutRequest;
      })
      .mockImplementationOnce(() => {
        loginSawAbortedLogout = logoutSignal?.aborted === true;
        return Promise.resolve(new Response(JSON.stringify({ owner: { id: "owner-2", email: "new@example.test" } }), { status: 200 }));
      });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole("heading", { name: "Thư viện truyện" });
    await user.click(screen.getByRole("button", { name: "Đăng xuất" }));
    await user.type(screen.getByLabelText("Email"), "new@example.test");
    await user.type(screen.getByLabelText("Mật khẩu"), "new-password");
    await user.click(screen.getByRole("button", { name: "Đăng nhập" }));
    await screen.findByRole("heading", { name: "Thư viện truyện" });
    expect(loginSawAbortedLogout).toBe(true);
    privateCache.set("new-session", { owner: "owner-2" });
    resolveLogout(new Response(null, { status: 204 }));
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(screen.getByText("new@example.test")).toBeInTheDocument();
    expect(privateCache.has("new-session")).toBe(true);
    expect(screen.queryByText("chưa xác nhận được đăng xuất")).not.toBeInTheDocument();
  });

  it("manages settings dialog focus, escape, and background isolation", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "owner-1", email: "owner@example.test" }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ mode: "economy", policy: "free_only", roles: {}, budgets: {} }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole("heading", { name: "Thư viện truyện" });
    const trigger = screen.getByRole("button", { name: "Cài đặt" });
    await user.click(trigger);
    const dialog = await screen.findByRole("dialog", { name: "Cài đặt" });
    expect(screen.getByRole("main").querySelector(".story-library")).toHaveAttribute("aria-hidden", "true");
    expect(dialog.querySelector("button")).toHaveFocus();
    const focusable = Array.from(dialog.querySelectorAll<HTMLElement>("button, input, select, textarea, [href], [tabindex]:not([tabindex='-1'])"));
    focusable.at(-1)?.focus();
    await user.keyboard("{Tab}");
    expect(dialog.querySelector("button")).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "Cài đặt" })).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it("hides the active campaign form when settings opens", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "owner-1", email: "owner@example.test" }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ mode: "economy", policy: "free_only", roles: {}, budgets: {} }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByRole("button", { name: "+ Tạo truyện mới" }));
    await user.type(screen.getByLabelText("Tên truyện"), "Bản nháp không mất");
    await user.click(screen.getByRole("button", { name: "Cài đặt" }));
    expect(screen.getByRole("dialog", { name: "Cài đặt" })).toBeInTheDocument();
    expect(screen.getByText("Tạo truyện mới").closest("section")).toHaveAttribute("aria-hidden", "true");
    await user.click(screen.getByRole("button", { name: "Đóng cài đặt" }));
    expect(screen.getByLabelText("Tên truyện")).toHaveValue("Bản nháp không mất");
  });
});
