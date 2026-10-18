import { Inflate } from "fflate";
import {
  ChatGptConversation,
  listChatGptConversations,
} from "./parseChatGptExport";

const MAX_INPUT_BYTES = 20 * 1024 * 1024;
const MAX_ENTRIES = 512;
const MAX_DECLARED_OUTPUT_BYTES = 60 * 1024 * 1024;
const MAX_CONVERSATION_BYTES = 20 * 1024 * 1024;
const ZIP_LOCAL = 0x04034b50;
const ZIP_CENTRAL = 0x02014b50;
const ZIP_END = 0x06054b50;
const ZIP64 = 0xffff;

const invalidArchive = () => new Error("ZIP không hợp lệ hoặc không an toàn. Hãy tạo lại bản xuất rồi thử lại.");
const invalidJson = () => new Error("Tệp JSON không hợp lệ hoặc không có thread ChatGPT hợp lệ.");
const limitError = (what: string) => new Error(`Tệp vượt quá giới hạn ${what}. Hãy chọn bản xuất nhỏ hơn.`);

interface ZipEntry {
  name: string;
  compressedSize: number;
  uncompressedSize: number;
  compression: number;
  crc: number;
  localOffset: number;
  dataOffset: number;
  dataEnd: number;
}

interface ReadBudget {
  entryCount: number;
  declaredTotal: number;
  actualTotal: number;
}

const readU16 = (data: Uint8Array, at: number) => data[at] | (data[at + 1] << 8);
const readU32 = (data: Uint8Array, at: number) => (readU16(data, at) + readU16(data, at + 2) * 0x10000) >>> 0;
const sameBytes = (a: Uint8Array, b: Uint8Array) => a.length === b.length && a.every((value, index) => value === b[index]);

function decodeName(bytes: Uint8Array): string {
  try {
    return new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  } catch {
    throw invalidArchive();
  }
}

function validateName(name: string): void {
  const parts = name.endsWith("/") ? name.slice(0, -1).split("/") : name.split("/");
  if (!name || name.includes("\\") || name.includes("\0") || name.startsWith("/") || /^[A-Za-z]:/.test(name) ||
      parts.some(part => !part || part === "." || part === "..")) {
    throw new Error("ZIP chứa đường dẫn không an toàn. Hãy tạo lại bản xuất rồi thử lại.");
  }
}

function crc32(data: Uint8Array): number {
  let crc = 0xffffffff;
  for (const byte of data) {
    crc ^= byte;
    for (let bit = 0; bit < 8; bit += 1) crc = (crc >>> 1) ^ ((crc & 1) ? 0xedb88320 : 0);
  }
  return (crc ^ 0xffffffff) >>> 0;
}

function findEndOfCentralDirectory(data: Uint8Array): number {
  const first = Math.max(0, data.length - 22 - 0xffff);
  for (let at = data.length - 22; at >= first; at -= 1) {
    if (readU32(data, at) === ZIP_END) return at;
  }
  throw invalidArchive();
}

function parseZipEntries(data: Uint8Array): ZipEntry[] {
  const end = findEndOfCentralDirectory(data);
  if (end + 22 > data.length || readU16(data, end + 4) !== 0 || readU16(data, end + 6) !== 0 ||
      readU16(data, end + 8) !== readU16(data, end + 10) ||
      readU16(data, end + 8) === ZIP64 || readU16(data, end + 10) === ZIP64 ||
      readU32(data, end + 12) === 0xffffffff || readU32(data, end + 16) === 0xffffffff ||
      end + 22 + readU16(data, end + 20) !== data.length) throw invalidArchive();
  const count = readU16(data, end + 10);
  const centralSize = readU32(data, end + 12);
  const centralOffset = readU32(data, end + 16);
  if (count > MAX_ENTRIES || centralOffset + centralSize !== end || centralOffset > data.length) throw limitError("số lượng entry hoặc cấu trúc ZIP");

  const entries: ZipEntry[] = [];
  const names = new Set<string>();
  let at = centralOffset;
  for (let index = 0; index < count; index += 1) {
    if (at + 46 > end || readU32(data, at) !== ZIP_CENTRAL) throw invalidArchive();
    const flags = readU16(data, at + 8);
    const compression = readU16(data, at + 10);
    const crc = readU32(data, at + 16);
    const compressedSize = readU32(data, at + 20);
    const uncompressedSize = readU32(data, at + 24);
    const nameLength = readU16(data, at + 28);
    const extraLength = readU16(data, at + 30);
    const commentLength = readU16(data, at + 32);
    const disk = readU16(data, at + 34);
    const externalAttributes = readU32(data, at + 38);
    const localOffset = readU32(data, at + 42);
    const nameBytes = data.subarray(at + 46, at + 46 + nameLength);
    const next = at + 46 + nameLength + extraLength + commentLength;
    if (next > end || (flags & 0x1) !== 0 || (flags & 0x8) !== 0 || (flags & ~0x800) !== 0 ||
        disk !== 0 || compressedSize === 0xffffffff || uncompressedSize === 0xffffffff ||
        (compression !== 0 && compression !== 8) || (externalAttributes >>> 16 & 0xf000) === 0xa000) throw invalidArchive();
    const name = decodeName(nameBytes);
    validateName(name);
    if (names.has(name)) throw new Error("ZIP có entry trùng tên. Hãy tạo lại bản xuất rồi thử lại.");
    names.add(name);
    if (localOffset + 30 > centralOffset || readU32(data, localOffset) !== ZIP_LOCAL) throw invalidArchive();
    const localNameLength = readU16(data, localOffset + 26);
    const localExtraLength = readU16(data, localOffset + 28);
    const localFlags = readU16(data, localOffset + 6);
    const localCompression = readU16(data, localOffset + 8);
    const localCrc = readU32(data, localOffset + 14);
    const localCompressedSize = readU32(data, localOffset + 18);
    const localUncompressedSize = readU32(data, localOffset + 22);
    const localName = data.subarray(localOffset + 30, localOffset + 30 + localNameLength);
    const dataOffset = localOffset + 30 + localNameLength + localExtraLength;
    const dataEnd = dataOffset + compressedSize;
    if (localFlags !== flags || localCompression !== compression || localCrc !== crc ||
        localCompressedSize !== compressedSize || localUncompressedSize !== uncompressedSize ||
        !sameBytes(localName, nameBytes) || dataOffset > centralOffset || dataEnd > centralOffset) throw invalidArchive();
    entries.push({ name, compressedSize, uncompressedSize, compression, crc, localOffset, dataOffset, dataEnd });
    at = next;
  }
  if (at !== end) throw invalidArchive();
  const sorted = [...entries].sort((a, b) => a.localOffset - b.localOffset);
  for (let index = 1; index < sorted.length; index += 1) {
    if (sorted[index - 1].dataEnd > sorted[index].localOffset || sorted[index - 1].localOffset === sorted[index].localOffset) throw invalidArchive();
  }
  return entries;
}

function isConversationName(name: string): boolean {
  return /(?:^|\/)conversations(?:[-_]\d+)?\.json$/i.test(name);
}

async function readZip(data: Uint8Array, budget: ReadBudget): Promise<string[]> {
  const entries = parseZipEntries(data);
  budget.entryCount += entries.length;
  if (budget.entryCount > MAX_ENTRIES) throw limitError("số lượng entry");
  const selected = new Map(entries.filter(entry => isConversationName(entry.name)).map(entry => [entry.name, entry]));
  if (!selected.size) throw new Error("Không tìm thấy tệp conversation trong ZIP. Hãy chọn bản xuất ChatGPT đầy đủ.");
  budget.declaredTotal += entries.reduce((total, entry) => total + entry.uncompressedSize, 0);
  if (budget.declaredTotal > MAX_DECLARED_OUTPUT_BYTES) throw limitError("dung lượng giải nén");
  const outputs = new Map<string, Uint8Array>();
  for (const entry of selected.values()) {
    if (entry.uncompressedSize > MAX_CONVERSATION_BYTES) throw limitError("mỗi tệp conversation");
    const chunks: Uint8Array[] = [];
    let size = 0;
    let finished = false;
    const ondata = (chunk: Uint8Array, final: boolean) => {
      size += chunk.length;
      budget.actualTotal += chunk.length;
      if (size > entry.uncompressedSize || size > MAX_CONVERSATION_BYTES || budget.actualTotal > MAX_DECLARED_OUTPUT_BYTES) throw limitError("dung lượng giải nén");
      chunks.push(chunk);
      if (final) finished = true;
    };
    try {
      if (entry.compression === 0) {
        for (let at = entry.dataOffset; at < entry.dataEnd; at += 4096) {
          ondata(data.subarray(at, Math.min(entry.dataEnd, at + 4096)), at + 4096 >= entry.dataEnd);
        }
      } else {
        const inflate = new Inflate({}, ondata);
        for (let at = entry.dataOffset; at < entry.dataEnd; at += 4096) {
          inflate.push(data.subarray(at, Math.min(entry.dataEnd, at + 4096)), at + 4096 >= entry.dataEnd);
        }
      }
    } catch (error) {
      if (error instanceof Error && error.message.includes("giới hạn")) throw error;
      throw invalidArchive();
    }
    if (!finished || size !== entry.uncompressedSize) throw invalidArchive();
    const output = new Uint8Array(size);
    let offset = 0;
    for (const part of chunks) { output.set(part, offset); offset += part.length; }
    if (crc32(output) !== entry.crc) throw invalidArchive();
    outputs.set(entry.name, output);
  }
  try {
    return [...selected.keys()].map(name => new TextDecoder("utf-8", { fatal: true }).decode(outputs.get(name)!));
  } catch {
    throw invalidJson();
  }
}

function deduplicate(conversations: ChatGptConversation[]): ChatGptConversation[] {
  const byId = new Map<string, { serialized: string; item: ChatGptConversation }>();
  for (const item of conversations) {
    const serialized = JSON.stringify(item);
    const previous = byId.get(item.id);
    if (previous && previous.serialized !== serialized) throw new Error("Các thread trùng ID có nội dung khác nhau. Hãy chọn bản xuất không bị trùng.");
    if (!previous) byId.set(item.id, { serialized, item });
  }
  return [...byId.values()].map(value => value.item);
}

/** Read local ChatGPT JSON/ZIP files without network access or partial results. */
export async function readChatGptExportFiles(files: File[]): Promise<ChatGptConversation[]> {
  if (!files.length) throw invalidJson();
  let announcedBytes = 0;
  for (const file of files) {
    if (!Number.isSafeInteger(file.size) || file.size < 0 || file.size > MAX_INPUT_BYTES) throw limitError("tổng dung lượng tệp");
    announcedBytes += file.size;
    if (announcedBytes > MAX_INPUT_BYTES) throw limitError("tổng dung lượng tệp");
  }
  const contents: Uint8Array[] = [];
  let totalBytes = 0;
  for (const file of files) {
    const bytes = new Uint8Array(await file.arrayBuffer());
    if (bytes.length !== file.size) throw invalidArchive();
    totalBytes += bytes.length;
    if (totalBytes > MAX_INPUT_BYTES) throw limitError("tổng dung lượng tệp");
    contents.push(bytes);
  }
  const jsonTexts: string[] = [];
  const budget: ReadBudget = { entryCount: 0, declaredTotal: 0, actualTotal: 0 };
  for (const bytes of contents) {
    const isZip = bytes.length >= 4 && bytes[0] === 0x50 && bytes[1] === 0x4b &&
      ((bytes[2] === 0x03 && bytes[3] === 0x04) || (bytes[2] === 0x05 && bytes[3] === 0x06) || (bytes[2] === 0x07 && bytes[3] === 0x08));
    if (isZip) jsonTexts.push(...await readZip(bytes, budget));
    else {
      if (bytes.length > MAX_CONVERSATION_BYTES) throw limitError("mỗi tệp conversation");
      try { jsonTexts.push(new TextDecoder("utf-8", { fatal: true }).decode(bytes)); }
      catch { throw invalidJson(); }
    }
  }
  const conversations: ChatGptConversation[] = [];
  for (const text of jsonTexts) {
    try { conversations.push(...listChatGptConversations(text)); }
    catch { throw invalidJson(); }
  }
  return deduplicate(conversations);
}
