export interface ChatGptConversation {
  id: string;
  title: string;
  mapping: Record<string, unknown>;
  current_node: string;
  [key: string]: unknown;
}

/** Parse an official ChatGPT conversations.json file locally.
 * Nothing is uploaded until the user explicitly previews ONE chosen thread.
 */
export function listChatGptConversations(text: string): ChatGptConversation[] {
  let decoded: unknown;
  try { decoded = JSON.parse(text); }
  catch { throw new Error("Tệp JSON không hợp lệ. Hãy giải nén ZIP và chọn conversations.json."); }
  const candidates = Array.isArray(decoded) ? decoded : (
    decoded && typeof decoded === "object" && "conversations" in decoded &&
    Array.isArray((decoded as { conversations?: unknown }).conversations)
      ? (decoded as { conversations: unknown[] }).conversations
      : [decoded]
  );
  const result = candidates.filter((item): item is ChatGptConversation => {
    if (!item || typeof item !== "object") return false;
    const itemLike = item as Partial<ChatGptConversation>;
    return typeof itemLike.id === "string" && typeof itemLike.title === "string" &&
      typeof itemLike.current_node === "string" &&
      Boolean(itemLike.mapping && typeof itemLike.mapping === "object");
  });
  if (!result.length) throw new Error("Không thấy thread ChatGPT hợp lệ có mapping/current_node.");
  return result;
}
