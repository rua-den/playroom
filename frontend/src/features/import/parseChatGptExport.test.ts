import { describe, expect, it } from "vitest";
import { listChatGptConversations } from "./parseChatGptExport";

describe("ChatGPT local export discovery", () => {
  const conversation = { id: "synthetic", title: "playrooom", current_node: "final", mapping: {
    root: { id: "root", message: null, parent: null },
    final: { id: "final", parent: "root", message: { author: { role: "user" }, content: { parts: ["hello"] } } },
  } };
  it("lists a matching user-chosen conversation from an account export without network calls", () => {
    expect(listChatGptConversations(JSON.stringify([{ ...conversation, title: "work" }, { ...conversation, id: "story" }])).map(item => item.title)).toEqual(["work", "playrooom"]);
  });
  it("handles a single selected conversation or wrapped conversations", () => {
    expect(listChatGptConversations(JSON.stringify(conversation))).toHaveLength(1);
    expect(listChatGptConversations(JSON.stringify({ conversations: [conversation] }))).toHaveLength(1);
  });
  it("rejects invalid formats, HTML and absent thread mapping", () => {
    expect(() => listChatGptConversations("<html/>")).toThrow("JSON");
    expect(() => listChatGptConversations(JSON.stringify([{ id: "no-mapping", title: "x" }]))).toThrow("mapping");
  });
});
