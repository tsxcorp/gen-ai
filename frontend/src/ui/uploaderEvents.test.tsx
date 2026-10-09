import { Children, isValidElement, type ReactElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from "vitest";
import { api } from "../api/client";
import type { Asset } from "../api/types";
import { ReferenceUpload } from "../panel/ReferenceUpload";
import { FileDropzone, type FileDropzoneProps } from "./FileDropzone";

const hooks = vi.hoisted(() => ({
  cursor: 0,
  slots: [] as { value: unknown; deps?: unknown[]; cleanup?: () => void }[],
  pending: [] as (() => void)[],
  dirty: false,
}));

vi.mock("react", async () => {
  const actual = await vi.importActual<typeof import("react")>("react");
  function effect(callback: () => void | (() => void), deps?: unknown[]) {
    const index = hooks.cursor++;
    const previous = hooks.slots[index];
    if (previous && deps && previous.deps && deps.length === previous.deps.length && deps.every((value, position) => Object.is(value, previous.deps?.[position]))) return;
    const slot = { value: undefined, deps, cleanup: previous?.cleanup };
    hooks.slots[index] = slot;
    hooks.pending.push(() => {
      slot.cleanup?.();
      slot.cleanup = callback() || undefined;
    });
  }
  return {
    ...actual,
    useId: () => "uploader-event-test",
    useState: (initial: unknown) => {
      const index = hooks.cursor++;
      const slot = hooks.slots[index] ?? { value: typeof initial === "function" ? initial() : initial };
      hooks.slots[index] = slot;
      return [slot.value, (next: unknown) => {
        const value = typeof next === "function" ? next(slot.value) : next;
        if (!Object.is(value, slot.value)) hooks.dirty = true;
        slot.value = value;
      }];
    },
    useRef: (initial: unknown) => {
      const index = hooks.cursor++;
      const slot = hooks.slots[index] ?? { value: { current: initial } };
      hooks.slots[index] = slot;
      return slot.value;
    },
    useEffect: effect,
    useLayoutEffect: effect,
  };
});

function render(component: () => ReactElement): ReactElement {
  for (let pass = 0; pass < 10; pass += 1) {
    hooks.cursor = 0;
    hooks.dirty = false;
    hooks.pending = [];
    const tree = component();
    hooks.pending.forEach((effect) => effect());
    if (!hooks.dirty) return tree;
  }
  throw new Error("Hook harness did not settle");
}

function unmount() {
  hooks.slots.forEach((slot) => slot.cleanup?.());
  hooks.slots = [];
}

function elements(tree: ReactNode): ReactElement<Record<string, unknown>>[] {
  return Children.toArray(tree).flatMap((child) => {
    if (!isValidElement<Record<string, unknown>>(child)) return [];
    return [child, ...elements(child.props.children as ReactNode)];
  });
}

function find(tree: ReactNode, predicate: (node: ReactElement<Record<string, unknown>>) => boolean) {
  const node = elements(tree).find(predicate);
  if (!node) throw new Error("Expected uploader element was not rendered");
  return node;
}

function fire(node: ReactElement<Record<string, unknown>>, name: string, event?: unknown) {
  const callback = node.props[name];
  if (typeof callback !== "function") throw new Error(`Missing ${name} handler`);
  callback(event);
}

const image = (name = "original.png") => new File([new Uint8Array([1, 2, 3])], name, { type: "image/png" });
const base: FileDropzoneProps = { accept: "image/*", maxBytes: 20 * 1024 * 1024, maxFiles: 2, label: "Chọn ảnh", onFiles: () => {}, pasteImages: true };
const zone = (tree: ReactNode) => find(tree, (node) => typeof node.props.onDrop === "function");
const picker = (tree: ReactNode) => find(tree, (node) => node.type === "input" && node.props.type === "file");
const clipboardItem = (file: File | null, type = file?.type ?? "image/png", kind = "file") => ({ kind, type, getAsFile: vi.fn(() => file) });

beforeEach(() => {
  hooks.slots = [];
  hooks.pending = [];
  hooks.cursor = 0;
});
afterEach(() => {
  unmount();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("FileDropzone real event paths with shallow hooks", () => {
  it("drag/drop prevents browser navigation and forwards original File identities in order", () => {
    const onFiles = vi.fn();
    const component = () => FileDropzone({ ...base, onFiles });
    const first = image();
    const second = image("second.png");
    const preventDefault = vi.fn();
    fire(zone(render(component)), "onDragOver", { preventDefault });
    expect(zone(render(component)).props.className).toContain("dragging");
    fire(zone(render(component)), "onDrop", { preventDefault, dataTransfer: { files: [first, second] } });
    expect(preventDefault).toHaveBeenCalledTimes(2);
    expect(onFiles).toHaveBeenCalledTimes(1);
    expect(onFiles.mock.calls[0]?.[0][0]).toBe(first);
    expect(onFiles.mock.calls[0]?.[0][1]).toBe(second);
    expect(zone(render(component)).props.className).not.toContain("dragging");
  });
  it("drag leave within the uploader preserves highlighting; leaving clears it", () => {
    const component = () => FileDropzone(base);
    fire(zone(render(component)), "onDragOver", { preventDefault: vi.fn() });
    fire(zone(render(component)), "onDragLeave", { currentTarget: { contains: () => true }, relatedTarget: {} });
    expect(zone(render(component)).props.className).toContain("dragging");
    fire(zone(render(component)), "onDragLeave", { currentTarget: { contains: () => false }, relatedTarget: null });
    expect(zone(render(component)).props.className).not.toContain("dragging");
  });
  it("paste forwards only image file items, ignores nulls, and retains the original File", () => {
    const original = image();
    const text = clipboardItem(new File(["text"], "text.txt", { type: "text/plain" }));
    const string = clipboardItem(null, "image/png", "string");
    const nullImage = clipboardItem(null);
    const onFiles = vi.fn();
    const preventDefault = vi.fn();
    const tree = render(() => FileDropzone({ ...base, onFiles }));
    fire(zone(tree), "onPaste", { preventDefault, clipboardData: { items: [text, string, nullImage, clipboardItem(original)] } });
    expect(onFiles).toHaveBeenCalledTimes(1);
    expect(onFiles.mock.calls[0]?.[0]).toHaveLength(1);
    expect(onFiles.mock.calls[0]?.[0][0]).toBe(original);
    expect(text.getAsFile).not.toHaveBeenCalled();
    expect(string.getAsFile).not.toHaveBeenCalled();
    expect(preventDefault).toHaveBeenCalledTimes(1);
  });
  it("does not intercept non-image clipboard contents or opt-out paste", () => {
    const onFiles = vi.fn();
    const preventDefault = vi.fn();
    fire(zone(render(() => FileDropzone({ ...base, onFiles }))), "onPaste", { preventDefault, clipboardData: { items: [clipboardItem(null, "text/plain", "string")] } });
    fire(zone(render(() => FileDropzone({ ...base, onFiles, pasteImages: false }))), "onPaste", { preventDefault, clipboardData: { items: [clipboardItem(image())] } });
    expect(onFiles).not.toHaveBeenCalled();
    expect(preventDefault).not.toHaveBeenCalled();
  });
  it.each([{ disabled: true }, { busy: true }])("locks drop, paste, picker change and picker click: %j", (state) => {
    const onFiles = vi.fn();
    const tree = render(() => FileDropzone({ ...base, ...state, onFiles }));
    const original = image();
    const preventDefault = vi.fn();
    fire(zone(tree), "onDrop", { preventDefault, dataTransfer: { files: [original] } });
    fire(zone(tree), "onPaste", { preventDefault, clipboardData: { items: [clipboardItem(original)] } });
    fire(picker(tree), "onChange", { target: { files: [original], value: "selected" } });
    const click = vi.fn();
    (picker(tree) as ReactElement & { ref: { current: unknown } }).ref.current = { click };
    fire(find(tree, (node) => node.type === "button"), "onClick");
    expect(onFiles).not.toHaveBeenCalled();
    expect(click).not.toHaveBeenCalled();
  });
  it("rejects overflow then accepts a valid picker selection and clears its error", () => {
    const onFiles = vi.fn();
    const component = () => FileDropzone({ ...base, maxFiles: 1, onFiles });
    fire(zone(render(component)), "onDrop", { preventDefault: vi.fn(), dataTransfer: { files: [image(), image("extra.png")] } });
    expect(onFiles).not.toHaveBeenCalled();
    expect(find(render(component), (node) => node.props.role === "alert").props.children).toEqual(expect.any(String));
    const original = image();
    const target = { files: [original], value: "selected" };
    fire(picker(render(component)), "onChange", { target });
    expect(onFiles).toHaveBeenCalledTimes(1);
    expect(onFiles.mock.calls[0]?.[0][0]).toBe(original);
    expect(target.value).toBe("");
    expect(elements(render(component)).some((node) => node.props.role === "alert")).toBe(false);
  });
  it("routes paste through file-count and MIME validation", () => {
    const onFiles = vi.fn();
    const component = () => FileDropzone({ ...base, accept: "image/png", maxFiles: 1, onFiles });
    fire(zone(render(component)), "onPaste", { preventDefault: vi.fn(), clipboardData: { items: [clipboardItem(image()), clipboardItem(image("extra.png"))] } });
    expect(onFiles).not.toHaveBeenCalled();
    fire(zone(render(component)), "onPaste", { preventDefault: vi.fn(), clipboardData: { items: [clipboardItem(new File(["data"], "photo.jpg", { type: "image/jpeg" }))] } });
    expect(onFiles).not.toHaveBeenCalled();
    expect(elements(render(component)).some((node) => node.props.role === "alert")).toBe(true);
  });
});

describe("ReferenceUpload consent and partial-failure lifecycle with shallow hooks", () => {
  let upload: MockInstance<typeof api.upload>;
  let revoke: MockInstance<typeof URL.revokeObjectURL>;
  beforeEach(() => {
    upload = vi.spyOn(api, "upload").mockRejectedValue(new Error("Unexpected test upload"));
    let nextUrl = 0;
    vi.spyOn(URL, "createObjectURL").mockImplementation(() => `blob:test-${++nextUrl}`);
    revoke = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
    vi.stubGlobal("Image", class {
      naturalWidth = 1600;
      naturalHeight = 900;
      onload: (() => void) | null = null;
      onerror: (() => void) | null = null;
      set src(_value: string) { queueMicrotask(() => this.onload?.()); }
    });
  });
  const stagedUploader = (tree: ReactNode) => find(tree, (node) => node.type === FileDropzone);
  const submit = (tree: ReactNode) => find(tree, (node) => node.props.className === "btn upload-submit");
  const consent = (tree: ReactNode) => elements(tree).filter((node) => node.type === "input" && node.props.type === "checkbox")[1]!;
  const param = { key: "reference_images", type: "imageList" as const, maxItems: 3 };

  it("stages previews without uploading and rejects a direct submit handler until consent", () => {
    const onChange = vi.fn();
    const component = () => ReferenceUpload({ param, value: undefined, onChange });
    fire(stagedUploader(render(component)), "onFiles", [image()]);
    const tree = render(component);
    expect(submit(tree).props.disabled).toBe(true);
    fire(submit(tree), "onClick");
    expect(upload).not.toHaveBeenCalled();
    expect(onChange).not.toHaveBeenCalled();
    expect(elements(tree).some((node) => node.type === "img" && node.props.src === "blob:test-1")).toBe(true);
  });
  it("uploads original files only after consent and carries source dimensions", async () => {
    upload.mockResolvedValue({ id: "uploaded", mime: "image/png" });
    const onChange = vi.fn();
    const original = image();
    const component = () => ReferenceUpload({ param, value: undefined, onChange });
    fire(stagedUploader(render(component)), "onFiles", [original]);
    fire(consent(render(component)), "onChange", { target: { checked: true } });
    fire(submit(render(component)), "onClick");
    await vi.waitFor(() => expect(onChange).toHaveBeenCalledTimes(1));
    expect(upload).toHaveBeenCalledWith(original, false, true);
    expect(upload.mock.calls[0]?.[0]).toBe(original);
    expect(onChange.mock.calls[0]?.[0]).toEqual([{ id: "uploaded", mime: "image/png", width: 1600, height: 900, name: original.name }]);
    expect(revoke).toHaveBeenCalledWith("blob:test-1");
  });
  it("keeps successful images and the failed staged image; retry does not duplicate the success", async () => {
    upload.mockResolvedValueOnce({ id: "first", mime: "image/png" }).mockRejectedValueOnce(new Error("Second upload failed")).mockResolvedValueOnce({ id: "second", mime: "image/png" });
    let value: Asset[] = [];
    const onChange = vi.fn((next: Asset | Asset[] | null) => { value = Array.isArray(next) ? next : []; });
    const firstFile = image("first.png");
    const secondFile = image("second.png");
    const component = () => ReferenceUpload({ param, value, onChange });
    fire(stagedUploader(render(component)), "onFiles", [firstFile, secondFile]);
    fire(consent(render(component)), "onChange", { target: { checked: true } });
    fire(submit(render(component)), "onClick");
    await vi.waitFor(() => expect(upload).toHaveBeenCalledTimes(2));
    await vi.waitFor(() => expect(find(render(component), (node) => node.props.role === "alert").props.children).toBe("Second upload failed"));
    expect(value.map((asset) => asset.id)).toEqual(["first"]);
    expect(revoke).toHaveBeenCalledWith("blob:test-1");
    expect(revoke).not.toHaveBeenCalledWith("blob:test-2");
    fire(submit(render(component)), "onClick");
    await vi.waitFor(() => expect(value.map((asset) => asset.id)).toEqual(["first", "second"]));
    expect(upload.mock.calls.map((call) => call[0])).toEqual([firstFile, secondFile, secondFile]);
  });
  it("prevents consecutive submit handlers from starting duplicate uploads", async () => {
    upload.mockResolvedValue({ id: "uploaded", mime: "image/png" });
    const onChange = vi.fn();
    const component = () => ReferenceUpload({ param, value: undefined, onChange });
    fire(stagedUploader(render(component)), "onFiles", [image()]);
    fire(consent(render(component)), "onChange", { target: { checked: true } });
    const button = submit(render(component));
    fire(button, "onClick");
    fire(button, "onClick");
    await vi.waitFor(() => expect(onChange).toHaveBeenCalledTimes(1));
    expect(upload).toHaveBeenCalledTimes(1);
  });
  it("disabled reference upload blocks direct submit even after consent", () => {
    let disabled = false;
    const onChange = vi.fn();
    const component = () => ReferenceUpload({ param, value: undefined, onChange, disabled });
    fire(stagedUploader(render(component)), "onFiles", [image()]);
    fire(consent(render(component)), "onChange", { target: { checked: true } });
    disabled = true;
    const tree = render(component);
    expect(submit(tree).props.disabled).toBe(true);
    fire(submit(tree), "onClick");
    expect(upload).not.toHaveBeenCalled();
    expect(onChange).not.toHaveBeenCalled();
  });
  it.each(["context change", "unmount"])("ignores a pending upload completion after %s", async (action) => {
    let finish!: (asset: Asset) => void;
    const pending = new Promise<Asset>((resolve) => { finish = resolve; });
    upload.mockReturnValue(pending);
    let contextKey = "original-model";
    const onChange = vi.fn();
    const component = () => ReferenceUpload({ param, value: undefined, onChange, contextKey });
    fire(stagedUploader(render(component)), "onFiles", [image()]);
    fire(consent(render(component)), "onChange", { target: { checked: true } });
    fire(submit(render(component)), "onClick");
    await vi.waitFor(() => expect(upload).toHaveBeenCalledTimes(1));
    if (action === "unmount") unmount();
    else {
      contextKey = "other-model";
      expect(elements(render(component)).some((node) => node.props.className === "btn upload-submit")).toBe(false);
    }
    finish({ id: "stale-upload", mime: "image/png" });
    await pending;
    await Promise.resolve();
    expect(onChange).not.toHaveBeenCalled();
    expect(revoke).toHaveBeenCalledWith("blob:test-1");
  });
  it("cleans partial previews when object URL creation fails without uploading", () => {
    vi.mocked(URL.createObjectURL).mockReturnValueOnce("blob:partial").mockImplementationOnce(() => { throw new Error("Preview unavailable"); });
    const component = () => ReferenceUpload({ param, value: undefined, onChange: vi.fn() });
    fire(stagedUploader(render(component)), "onFiles", [image(), image("second.png")]);
    expect(revoke).toHaveBeenCalledWith("blob:partial");
    expect(elements(render(component)).some((node) => node.props.role === "alert")).toBe(true);
    expect(upload).not.toHaveBeenCalled();
  });
  it("revokes previews on replacement, removal and unmount, resetting consent", () => {
    const component = () => ReferenceUpload({ param, value: undefined, onChange: vi.fn() });
    fire(stagedUploader(render(component)), "onFiles", [image()]);
    fire(consent(render(component)), "onChange", { target: { checked: true } });
    fire(stagedUploader(render(component)), "onFiles", [image("replacement.png")]);
    expect(revoke).toHaveBeenCalledWith("blob:test-1");
    expect(consent(render(component)).props.checked).toBe(false);
    fire(find(render(component), (node) => node.props["aria-label"] === "Gỡ file replacement.png"), "onClick");
    expect(revoke).toHaveBeenCalledWith("blob:test-2");
    fire(stagedUploader(render(component)), "onFiles", [image("unmount.png")]);
    unmount();
    expect(revoke).toHaveBeenCalledWith("blob:test-3");
  });
});
