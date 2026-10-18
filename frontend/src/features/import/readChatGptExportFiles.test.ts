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

const signature = (data: Uint8Array, a: number, b: number, c: number, d: number) =>
  data.findIndex((value, index) => value === a && data[index + 1] === b && data[index + 2] === c && data[index + 3] === d);
const putU32 = (data: Uint8Array, at: number, value: number) => {
  data[at] = value & 0xff;
  data[at + 1] = (value >>> 8) & 0xff;
  data[at + 2] = (value >>> 16) & 0xff;
  data[at + 3] = (value >>> 24) & 0xff;
};
const putU16 = (data: Uint8Array, at: number, value: number) => {
  data[at] = value & 0xff;
  data[at + 1] = (value >>> 8) & 0xff;
};
const mutateEntry = (data: Uint8Array, name: string, mutate: (central: number, local: number) => void) => {
  const central = signature(data, 0x50, 0x4b, 0x01, 0x02);
  const nameLength = data[central + 28] | (data[central + 29] << 8);
  const decoded = new TextDecoder().decode(data.subarray(central + 46, central + 46 + nameLength));
  if (decoded !== name) throw new Error(`unexpected fixture entry ${decoded}`);
  const local = data[central + 42] | (data[central + 43] << 8) | (data[central + 44] << 16) | (data[central + 45] << 24);
  mutate(central, local);
};

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
    const crcLocal = crc.findIndex((value, index) => value === 0x50 && crc[index + 1] === 0x4b && crc[index + 2] === 0x03 && crc[index + 3] === 0x04);
    crc[crcLocal + 14] ^= 1;
    await expect(readChatGptExportFiles([new File([crc], "crc.zip")])).rejects.toThrow("ZIP");
  });

  it("accepts standard DEFLATE fast/max option bits when central and local flags match", async () => {
    const data = new Uint8Array(await zipFile({ "conversations.json": JSON.stringify([conversation("flags")]) }).arrayBuffer());
    mutateEntry(data, "conversations.json", (central, local) => {
      putU16(data, central + 8, 0x806);
      putU16(data, local + 6, 0x806);
    });
    expect((await readChatGptExportFiles([new File([data], "flags.zip")]))[0].id).toBe("flags");
  });

  it("rejects DEFLATE option bits on stored entries", async () => {
    const stored = new Uint8Array(await new File([new Uint8Array(zipSync({
      "conversations.json": new Uint8Array(strToU8(JSON.stringify([conversation("stored")]))),
    }, { level: 0 }))], "stored.zip").arrayBuffer());
    mutateEntry(stored, "conversations.json", (central, local) => {
      putU16(stored, central + 8, 0x806);
      putU16(stored, local + 6, 0x806);
    });
    await expect(readChatGptExportFiles([new File([stored], "stored.zip")])).rejects.toThrow("ZIP");
  });

  it("rejects symlink metadata and a false small uncompressed size after actual inflation", async () => {
    const symlink = new Uint8Array(await zipFile({ "conversations.json": JSON.stringify([conversation("link")]) }).arrayBuffer());
    mutateEntry(symlink, "conversations.json", central => putU32(symlink, central + 38, 0xa0000000));
    await expect(readChatGptExportFiles([new File([symlink], "symlink.zip")])).rejects.toThrow("ZIP");
    const large = JSON.stringify([conversation("bomb", "x".repeat(2 * 1024 * 1024))]);
    const bomb = new Uint8Array(await zipFile({ "conversations.json": large }).arrayBuffer());
    mutateEntry(bomb, "conversations.json", (central, local) => {
      putU32(bomb, central + 24, 1);
      putU32(bomb, local + 22, 1);
    });
    await expect(readChatGptExportFiles([new File([bomb], "bomb.zip")])).rejects.toThrow("giới hạn");
  });

  it("rejects declared output totals across ZIP inputs and EOCD count mismatches", async () => {
    const makeArchive = async (id: string) => new Uint8Array(await zipFile({
      "account.json": "{}",
      "conversations.json": JSON.stringify([conversation(id)]),
    }).arrayBuffer());
    const first = await makeArchive("declared-one");
    const second = await makeArchive("declared-two");
    mutateEntry(first, "account.json", (central, local) => {
      putU32(first, central + 24, 40 * 1024 * 1024);
      putU32(first, local + 22, 40 * 1024 * 1024);
    });
    mutateEntry(second, "account.json", (central, local) => {
      putU32(second, central + 24, 40 * 1024 * 1024);
      putU32(second, local + 22, 40 * 1024 * 1024);
    });
    await expect(readChatGptExportFiles([new File([first], "one.zip"), new File([second], "two.zip")])).rejects.toThrow("dung lượng");
    const count = new Uint8Array(await zipFile({ "conversations.json": JSON.stringify([conversation("count")]) }).arrayBuffer());
    const end = count.length - 22;
    putU16(count, end + 8, 0);
    await expect(readChatGptExportFiles([new File([count], "count.zip")])).rejects.toThrow("ZIP");
  });

  it("supports Unicode and newlines in stored conversation JSON", async () => {
    const json = JSON.stringify([conversation("unicode", "Xin chào\n世界")]);
    const bytes = new Uint8Array(zipSync({ "conversations.json": new Uint8Array(strToU8(json)) }, { level: 0 }));
    expect((await readChatGptExportFiles([new File([bytes], "stored-unicode.zip")]))[0].title).toBe("Xin chào\n世界");
  });

  it("reads multiple selected JSON inputs locally", async () => {
    const files = [
      new File([JSON.stringify([conversation("one")])], "conversations.json", { type: "application/json" }),
      new File([JSON.stringify([conversation("two")])], "conversations-1.json", { type: "application/json" }),
    ];
    expect((await readChatGptExportFiles(files)).map(item => item.id)).toEqual(["one", "two"]);
  });
});
