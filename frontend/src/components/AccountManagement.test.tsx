import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api } from "../api/client";
import { AccountManagementPage } from "./AccountManagement";

afterEach(() => vi.restoreAllMocks());

describe("account management", () => {
  it("creates and edits accounts, and confirms deletion before removing another account", async () => {
    const list = vi.spyOn(api, "listAccounts").mockResolvedValue([
      { id: "admin-id", username: "admin", is_admin: true, created_at: "2026-10-27T00:00:00Z" },
    ]);
    const create = vi.spyOn(api, "createAccount").mockResolvedValue({ id: "user-id", username: "reader", is_admin: false, created_at: "2026-10-27T00:00:00Z" });
    const update = vi.spyOn(api, "updateAccount").mockResolvedValue({ id: "user-id", username: "reader2", is_admin: false, created_at: "2026-10-27T00:00:00Z" });
    const remove = vi.spyOn(api, "deleteAccount").mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(<AccountManagementPage currentOwnerId="admin-id" onBack={() => undefined} />);

    await screen.findByRole("heading", { name: "Quản lý tài khoản" });
    await user.type(screen.getByLabelText("Tên đăng nhập"), "reader");
    await user.type(screen.getByLabelText("Mật khẩu"), "reader password long");
    await user.click(screen.getByRole("button", { name: "Tạo tài khoản" }));
    await waitFor(() => expect(create).toHaveBeenCalledWith({ username: "reader", password: "reader password long" }));
    expect(list).toHaveBeenCalledOnce();
    expect(screen.getByText("reader")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Sửa reader" }));
    const editForm = screen.getByRole("form", { name: "Sửa tài khoản" });
    await user.clear(within(editForm).getByLabelText("Tên đăng nhập"));
    await user.type(within(editForm).getByLabelText("Tên đăng nhập"), "reader2");
    await user.click(within(editForm).getByRole("button", { name: "Lưu thay đổi" }));
    await waitFor(() => expect(update).toHaveBeenCalledWith("user-id", { username: "reader2", password: undefined }));

    await user.click(screen.getByRole("button", { name: "Xóa reader2" }));
    expect(screen.getByText(/xóa toàn bộ truyện và dữ liệu/i)).toBeInTheDocument();
    expect(remove).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Xác nhận xóa reader2" }));
    await waitFor(() => expect(remove).toHaveBeenCalledWith("user-id"));
    expect(screen.queryByText("reader2")).not.toBeInTheDocument();
  });

  it("does not offer deleting the signed-in admin account", async () => {
    vi.spyOn(api, "listAccounts").mockResolvedValue([
      { id: "admin-id", username: "admin", is_admin: true, created_at: "2026-10-27T00:00:00Z" },
    ]);
    render(<AccountManagementPage currentOwnerId="admin-id" onBack={() => undefined} />);
    await screen.findByText("admin");
    expect(screen.queryByRole("button", { name: "Xóa admin" })).not.toBeInTheDocument();
  });
});
