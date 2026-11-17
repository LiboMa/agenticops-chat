import { describe, expect, it } from "vitest";
import { ApiError, errorFromBody } from "@/api/client";

describe("errorFromBody — a refusal's body as the error the pages read", () => {
  it("keeps the code of the contract's UiError, wherever the server put it", () => {
    // FastAPI's HTTPException(detail={detail, code}) nests it …
    const nested = errorFromBody(409, { detail: { detail: "Translation in flight", code: "in_flight", refs: [1] } }, "Conflict");
    expect([nested.status, nested.message, nested.code, nested.data]).toEqual([409, "Translation in flight", "in_flight", { detail: "Translation in flight", code: "in_flight", refs: [1] }]);
    // … a JSONResponse puts it at the top. MVP-2.9.0: agent_run_in_flight, rca_changed and status_moved are sent
    // this way, and the client dropped their code — the page could not tell which refusal it was
    const top = errorFromBody(409, { detail: "The diagnosis changed: RCA #6 is now the newest.", code: "rca_changed", rca_id: 6 }, "Conflict");
    expect(top).toBeInstanceOf(ApiError);
    expect([top.status, top.message, top.code]).toEqual([409, "The diagnosis changed: RCA #6 is now the newest.", "rca_changed"]);
    expect(top.data).toEqual({ detail: "The diagnosis changed: RCA #6 is now the newest.", code: "rca_changed", rca_id: 6 });
  });

  it("reads everything else as before: a plain sentence, a 422 list, a body with no detail", () => {
    const plain = errorFromBody(409, { detail: "Fix plan is already approved" }, "Conflict");
    expect([plain.message, plain.code, plain.data]).toEqual(["Fix plan is already approved", undefined, undefined]);
    expect(errorFromBody(422, { detail: [{ loc: ["body", "reason"], msg: "Field required" }] }, "Unprocessable").message).toBe("reason: Field required");
    expect(errorFromBody(500, {}, "Internal Server Error").message).toBe("Internal Server Error");
    expect(errorFromBody(400, { error: "bad thing" }, "Bad Request").message).toBe("bad thing");
    expect(errorFromBody(409, { detail: "x", code: 7 }, "Conflict").code).toBeUndefined();          // a code is a string
  });
});
