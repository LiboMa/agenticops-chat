import { describe, it, expect } from "vitest";
import { destinationOf, publishableChannels } from "@/lib/publish";
import type { NotificationChannel } from "@/api/types";

const ch = (x: Partial<NotificationChannel>) => ({ name: "c", channel_type: "sns-report", config: {}, severity_filter: [], is_enabled: true, ...x }) as NotificationChannel;

describe("publish (MVP-2.7.0 S6)", () => {
  it("names the real destination before anything is sent", () => {
    expect(destinationOf(ch({ config: { topic_arn: "arn:aws:sns:us-east-1:1:ops" } }))).toBe("arn:aws:sns:us-east-1:1:ops");
    expect(destinationOf(ch({ channel_type: "ses", config: { recipients: ["a@x.com", "b@y.com"] } }))).toBe("a@x.com, b@y.com");
    expect(destinationOf(ch({ channel_type: "ses", config: { recipients: "a@x.com" } }))).toBe("a@x.com");
    expect(destinationOf(ch({ config: {} }))).toBe("");
  });
  it("only enabled sns-report / ses channels publish", () => {
    const list = [ch({ name: "a" }), ch({ name: "b", channel_type: "ses" }), ch({ name: "c", channel_type: "slack" as never }),
                  ch({ name: "d", is_enabled: false })];
    expect(publishableChannels(list).map((c) => c.name)).toEqual(["a", "b"]);
  });
});
