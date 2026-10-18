import { describe, expect, it } from "vitest";
import { zipSync, strToU8 } from "fflate";
import { readChatGptExportFiles } from "./readChatGptExportFiles";

const conversation = (id: string, title = id) => ({
  id,
  title,
  current_node: "final",
  mapping: { final: { id: "final", message: null, parent: null } },
});

const zipFile = (entries: Record<string, Uint8Array | string>) => new File([
  // Keep synthetic ZIP values as raw bytes; fflate treats plain objects as directories.
  new Uint8Array(zipSync(Object.fromEntries(Object.entries(entries).map(([name, value]) => [
    name,
    typeof value === "string" ? new Uint8Array(strToU8(value)) : new Uint8Array(value),
  ])) as Record<string, Uint8Array>, { level: 6 })),
], "export.zip", { type: "application/zip" });

describe("ChatGPT export file discovery", () => {
  it("reads conversations.json and numbered conversation files while ignoring attachments", async () => {
    const result = await readChatGptExportFiles([zipFile({
      "conversations.json": JSON.stringify([conversation("one")]),
      "conversations-1.json": JSON.stringify([conversation("two")]),
      "assets/image.png": new Uint8Array([1, 2, 3]),
      "account.json": JSON.stringify({ email: "private@example.test" }),
    })]);
    expect(result.map(item => item.id)).toEqual(["one", "two"]);
  });

  it("accepts nested safe conversation filenames and deduplicates identical ids", async () => {
    const result = await readChatGptExportFiles([zipFile({
      "nested/conversations.json": JSON.stringify([conversation("one")]),
      "nested/conversations_1.json": JSON.stringify([conversation("one")]),
    })]);
    expect(result).toHaveLength(1);
  });

  it("rejects conflicting duplicate ids", async () => {
    await expect(readChatGptExportFiles([zipFile({
      "conversations.json": JSON.stringify([conversation("same", "first")]),
      "conversations-1.json": JSON.stringify([conversation("same", "second")]),
    })])).rejects.toThrow("trùng");
  });

  it("rejects traversal, entry and archive limits before returning partial results", async () => {
    await expect(readChatGptExportFiles([zipFile({
      "../conversations.json": JSON.stringify([conversation("unsafe")]),
    })])).rejects.toThrow("đường dẫn");
    const tooMany = Object.fromEntries(Array.from({ length: 513 }, (_, index) => [
      `file-${index}.txt`, "x",
    ]));
    await expect(readChatGptExportFiles([zipFile(tooMany)])).rejects.toThrow("số lượng");
  });

  it("rejects a ZIP without a discoverable conversation JSON", async () => {
    await expect(readChatGptExportFiles([zipFile({ "account.json": "{}", "assets/photo.png": new Uint8Array([1]) })]))
      .rejects.toThrow("conversation");
  });

  it("rejects encrypted and unsupported compression metadata", async () => {
    const encrypted = new Uint8Array(await zipFile({ "conversations.json": "[]" }).arrayBuffer());
    const central = encrypted.findIndex((value, index) => value === 0x50 && encrypted[index + 1] === 0x4b && encrypted[index + 2] === 0x01 && encrypted[index + 3] === 0x02);
    encrypted[central + 8] |= 1;
    await expect(readChatGptExportFiles([new File([encrypted], "encrypted.zip")])).rejects.toThrow("ZIP");
    const unsupported = new Uint8Array(await zipFile({ "conversations.json": "[]" }).arrayBuffer());
    const unsupportedCentral = unsupported.findIndex((value, index) => value === 0x50 && unsupported[index + 1] === 0x4b && unsupported[index + 2] === 0x01 && unsupported[index + 3] === 0x02);
    unsupported[unsupportedCentral + 10] = 12;
    await expect(readChatGptExportFiles([new File([unsupported], "unsupported.zip")])).rejects.toThrow("ZIP");
  });

  it("checks declared input size before reading file bytes", async () => {
    let reads = 0;
    const oversized = {
      size: 20 * 1024 * 1024 + 1,
      arrayBuffer: async () => { reads += 1; return new ArrayBuffer(0); },
    } as unknown as File;
    await expect(readChatGptExportFiles([oversized])).rejects.toThrow("giới hạn");
    expect(reads).toBe(0);
  });

  it("applies the entry limit across multiple ZIP inputs", async () => {
    const makeArchive = (offset: number) => zipFile(Object.fromEntries([
      ["conversations.json", JSON.stringify([conversation(`aggregate-${offset}`)])],
      ...Array.from({ length: 300 }, (_, index) => [`assets/${offset}-${index}.bin`, new Uint8Array([index])]),
    ]));
    await expect(readChatGptExportFiles([makeArchive(1), makeArchive(2)])).rejects.toThrow("số lượng entry");
  });

  it("rejects truncated archives, local-header mismatches, and CRC corruption", async () => {
    const source = new Uint8Array(await zipFile({ "conversations.json": JSON.stringify([conversation("crc")]) }).arrayBuffer());
    await expect(readChatGptExportFiles([new File([source.slice(0, -1)], "truncated.zip")])).rejects.toThrow("ZIP");
    const localMismatch = source.slice();
    const local = localMismatch.findIndex((value, index) => value === 0x50 && localMismatch[index + 1] === 0x4b && localMismatch[index + 2] === 0x03 && localMismatch[index + 3] === 0x04);
    localMismatch[local + 8] ^= 8;
    await expect(readChatGptExportFiles([new File([localMismatch], "mismatch.zip")])).rejects.toThrow("ZIP");
    const crc = source.slice();
    const central = crc.findIndex((value, index) => value === 0x50 && crc[index + 1] === 0x4b && crc[index + 2] === 0x01 && crc[index + 3] === 0x02);
    crc[central + 16] ^= 1;
    await expect(readChatGptExportFiles([new File([crc], "crc.zip")])).rejects.toThrow("ZIP");
  });

  it("reads multiple selected JSON inputs locally", async () => {
    const files = [
      new File([JSON.stringify([conversation("one")])], "conversations.json", { type: "application/json" }),
      new File([JSON.stringify([conversation("two")])], "conversations-1.json", { type: "application/json" }),
    ];
    expect((await readChatGptExportFiles(files)).map(item => item.id)).toEqual(["one", "two"]);
  });
});
