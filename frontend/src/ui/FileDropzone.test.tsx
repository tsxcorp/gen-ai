import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { FileDropzone, validateFiles } from "./FileDropzone";

const limit = 20 * 1024 * 1024;
const file = (name = "image.png", type = "image/png", size = 3) => new File([new Uint8Array(size)], name, { type });
const props = { accept: "image/*", maxBytes: limit, maxFiles: 2, label: "Chọn ảnh", onFiles: () => {} };

describe("shared file validation (requirements #11)", () => {
  it("accepts image MIME types without changing original files", () => {
    const image = file();
    expect(validateFiles([image], "image/*", limit, 1)).toBeNull();
    expect(image.name).toBe("image.png");
    expect(image.size).toBe(3);
  });
  it("accepts exactly 20 MB but rejects one byte above", () => {
    expect(validateFiles([file("limit.png", "image/png", limit)], "image/*", limit, 1)).toBeNull();
    expect(validateFiles([file("large.png", "image/png", limit + 1)], "image/*", limit, 1)).toEqual(expect.any(String));
  });
  it("enforces maxItems inclusively", () => {
    expect(validateFiles([file(), file("second.png")], "image/*", limit, 2)).toBeNull();
    expect(validateFiles([file(), file("second.png"), file("third.png")], "image/*", limit, 2)).toEqual(expect.any(String));
    expect(validateFiles([file()], "image/*", limit, 0)).toEqual(expect.any(String));
  });
  it("rejects no files and empty files", () => {
    expect(validateFiles([], "image/*", limit, 1)).toEqual(expect.any(String));
    expect(validateFiles([file("empty.png", "image/png", 0)], "image/*", limit, 1)).toEqual(expect.any(String));
  });
  it("checks every file, not only the first", () => {
    expect(validateFiles([file(), file("text.txt", "text/plain")], "image/*", limit, 2)).toEqual(expect.any(String));
    expect(validateFiles([file(), file("empty.png", "image/png", 0)], "image/*", limit, 2)).toEqual(expect.any(String));
  });
  it("accepts JSON extension with empty MIME and exact MIME with normalized accept tokens", () => {
    expect(validateFiles([file("KEY.JSON", "")], ".json, application/json", limit, 1)).toBeNull();
    expect(validateFiles([file("key", "application/json")], " .JSON , APPLICATION/JSON ", limit, 1)).toBeNull();
    expect(validateFiles([file("key.json.exe", "")], ".json", limit, 1)).toEqual(expect.any(String));
  });
  it("does not mistake lookalike MIME types or filenames for images", () => {
    expect(validateFiles([file("fake.png", "text/plain")], "image/*", limit, 1)).toEqual(expect.any(String));
    expect(validateFiles([file("fake.png", "imagefake/png")], "image/*", limit, 1)).toEqual(expect.any(String));
    expect(validateFiles([file("fake.png", "image/png-extra")], "image/png", limit, 1)).toEqual(expect.any(String));
  });
});

describe("uploader accessible server-rendered contract", () => {
  it("renders a keyboard-native picker and accepted file input", () => {
    const html = renderToStaticMarkup(<FileDropzone {...props} pasteImages />);
    expect(html).toMatch(/<button[^>]*type="button"/);
    expect(html).toContain('type="file"');
    expect(html).toContain('accept="image/*"');
    expect(html).toContain('aria-label="Chọn ảnh"');
    expect(html).toContain('aria-describedby=');
    expect(html).toContain('multiple=""');
    expect(html).toContain("Ctrl/Cmd+V");
  });
  it.each([{ disabled: true }, { busy: true }])("disables both picker and file input while locked", (state) => {
    const html = renderToStaticMarkup(<FileDropzone {...props} {...state} />);
    expect(html).toMatch(/<button[^>]*disabled=""/);
    expect(html).toMatch(/<input[^>]*disabled=""/);
    if ("busy" in state) expect(html).toContain('aria-busy="true"');
  });
  it("JSON picker is single-file, has no image-paste hint, and never previews secret content", () => {
    const key = new File(['{"private_key":"DO-NOT-RENDER"}'], "service-account.json", { type: "application/json" });
    const html = renderToStaticMarkup(<FileDropzone {...props} accept=".json,application/json" maxFiles={1} selectedFiles={[key]} />);
    expect(html).toContain("service-account.json");
    expect(html).not.toContain("DO-NOT-RENDER");
    expect(html).not.toContain("private_key");
    expect(html).not.toContain("multiple=");
    expect(html).not.toContain("Ctrl/Cmd+V");
  });
  it("does not invoke file callbacks during rendering", () => {
    let calls = 0;
    renderToStaticMarkup(<FileDropzone {...props} selectedFiles={[file()]} onFiles={() => { calls += 1; }} />);
    expect(calls).toBe(0);
  });
});
