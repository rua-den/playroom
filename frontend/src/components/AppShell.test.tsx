import { describe, expect, it } from "vitest";
import { recoverableJobCount, recoverableJobSummary } from "./AppShell";

describe("recoverable job summary", () => {
  it("counts only jobs that can still be recovered", () => {
    const jobs = ["queued", "running", "cancelling", "interrupted", "candidate", "committed", "failed", "cancelled"];
    expect(recoverableJobCount(jobs.map((status) => ({ status })))).toBe(5);
  });

  it("makes the recent jobs query cap explicit in the summary", () => {
    expect(recoverableJobSummary(3)).toBe("Có thể khôi phục trong danh sách (tối đa 20 việc): 3");
  });
});
