import { describe, it, expect } from "vitest";
import { channelFields, appFields, missingRequired, buildConfigPayload, type MessagingSchema } from "@/lib/messagingFields";

const SCHEMA: MessagingSchema = {
  app_platforms: [
    { platform: "feishu", label: "Feishu", fields: [
      { key: "app_id", label: "App ID", type: "text", required: true, secret: false },
      { key: "app_secret", label: "App Secret", type: "password", required: true, secret: true },
    ]},
  ],
  channel_types: [
    { type: "ses", label: "SES", fields: [
      { key: "sender", label: "Sender", type: "text", required: true, secret: false },
      { key: "recipients", label: "Recipients", type: "list", required: true, secret: false },
      { key: "region", label: "Region", type: "text", required: true, secret: false },
    ]},
  ],
};

describe("messagingFields", () => {
  it("channelFields / appFields look up by type/platform", () => {
    expect(channelFields(SCHEMA, "ses").map((f) => f.key)).toEqual(["sender", "recipients", "region"]);
    expect(appFields(SCHEMA, "feishu").map((f) => f.key)).toEqual(["app_id", "app_secret"]);
    expect(channelFields(SCHEMA, "nope")).toEqual([]);
    expect(channelFields(undefined, "ses")).toEqual([]);
  });

  it("missingRequired flags blank required fields", () => {
    const f = channelFields(SCHEMA, "ses");
    expect(missingRequired(f, { sender: "a@b.com" })).toEqual(["recipients", "region"]);
    expect(missingRequired(f, { sender: "a@b.com", recipients: "x", region: "us-east-1" })).toEqual([]);
  });

  it("buildConfigPayload splits list fields and casts numbers", () => {
    const f = channelFields(SCHEMA, "ses");
    const p = buildConfigPayload(f, { sender: "a@b.com", recipients: "x@y.com, z@w.com", region: "us-east-1" });
    expect(p.recipients).toEqual(["x@y.com", "z@w.com"]);
    expect(p.sender).toBe("a@b.com");
  });

  it("buildConfigPayload OMITS blank secret fields (keep-existing)", () => {
    const f = appFields(SCHEMA, "feishu");
    const p = buildConfigPayload(f, { app_id: "cli_x", app_secret: "" });
    expect(p.app_id).toBe("cli_x");
    expect("app_secret" in p).toBe(false); // omitted → backend keeps existing
  });
});
