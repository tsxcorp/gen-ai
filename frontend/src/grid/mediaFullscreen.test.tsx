import { renderToStaticMarkup } from "react-dom/server";
import { Children, isValidElement, type ReactElement, type ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Asset } from "../api/types";
import { AssetView } from "./AssetView";
import { MediaViewer } from "./MediaViewer";

const lifecycle = vi.hoisted(() => ({
  active: false,
  cursor: 0,
  slots: [] as { value: unknown; cleanup?: () => void }[],
  pending: [] as (() => void)[],
}));

vi.mock("react", async () => {
  const actual = await vi.importActual<typeof import("react")>("react");
  return {
    ...actual,
    useRef: (initial: unknown) => {
      if (!lifecycle.active) return actual.useRef(initial);
      const index = lifecycle.cursor++;
      const slot = lifecycle.slots[index] ?? { value: { current: initial } };
      lifecycle.slots[index] = slot;
      return slot.value;
    },
    useState: (initial: unknown) => {
      if (!lifecycle.active) return actual.useState(initial);
      const index = lifecycle.cursor++;
      const slot = lifecycle.slots[index] ?? { value: initial };
      lifecycle.slots[index] = slot;
      return [slot.value, (next: unknown) => { slot.value = next; }];
    },
    useEffect: (callback: () => void | (() => void), deps?: unknown[]) => {
      if (!lifecycle.active) return actual.useEffect(callback, deps);
      const index = lifecycle.cursor++;
      if (lifecycle.slots[index]) return;
      const slot: { value: unknown; cleanup?: () => void } = { value: undefined };
      lifecycle.slots[index] = slot;
      lifecycle.pending.push(() => { slot.cleanup = callback() || undefined; });
    },
  };
});

vi.mock("react-dom", async () => {
  const actual = await vi.importActual<typeof import("react-dom")>("react-dom");
  return { ...actual, createPortal: (...args: Parameters<typeof actual.createPortal>) => lifecycle.active ? args[0] : actual.createPortal(...args) };
});

function nodes(tree: ReactNode): ReactElement<Record<string, unknown>>[] {
  return Children.toArray(tree).flatMap((child) => isValidElement<Record<string, unknown>>(child)
    ? [child, ...nodes(child.props.children as ReactNode)] : []);
}

function teardown() {
  lifecycle.slots.forEach((slot) => { slot.cleanup?.(); slot.cleanup = undefined; });
}

afterEach(() => {
  teardown();
  lifecycle.active = false;
  lifecycle.slots = [];
  lifecycle.pending = [];
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function mountViewer(asset = image, alt = "Kết quả", explicitOpener = false) {
  const windowEvents = new Map<string, (event: Record<string, unknown>) => void>();
  const documentEvents = new Map<string, (event: Record<string, unknown>) => void>();
  const browserDocument = {
    activeElement: null as ElementStub | null,
    fullscreenElement: null as ElementStub | null,
    body: { children: [] as ElementStub[], style: { overflow: "scroll" } },
    exitFullscreen: vi.fn(async () => { browserDocument.fullscreenElement = null; }),
    addEventListener: vi.fn((name: string, callback: (event: Record<string, unknown>) => void) => documentEvents.set(name, callback)),
    removeEventListener: vi.fn((name: string) => documentEvents.delete(name)),
  };
  class ElementStub {
    inert = false;
    isConnected = true;
    children: ElementStub[] = [];
    tag = "button";
    controls = false;
    requestFullscreen: (() => Promise<void>) | undefined = vi.fn(async () => {});
    focus = vi.fn(() => { browserDocument.activeElement = this; });
    contains = (target: unknown): boolean => target === this || this.children.includes(target as ElementStub);
    querySelectorAll = vi.fn((selector: string) => this.children.filter((child) =>
      child.tag === "button" || (selector.includes("video[controls]") && child.tag === "video" && child.controls)));
  }
  const opener = new ElementStub();
  const incidentalFocus = new ElementStub();
  const background = new ElementStub();
  const alreadyInert = new ElementStub();
  alreadyInert.inert = true;
  const viewer = new ElementStub();
  const fullscreenButton = new ElementStub();
  const close = new ElementStub();
  const videoElement = new ElementStub();
  videoElement.tag = "video";
  videoElement.controls = true;
  viewer.children = asset.mime.startsWith("video/") ? [fullscreenButton, close, videoElement] : [fullscreenButton, close];
  browserDocument.body.children = [background, alreadyInert, viewer];
  browserDocument.activeElement = explicitOpener ? incidentalFocus : opener;
  const browserWindow = {
    addEventListener: vi.fn((name: string, callback: (event: Record<string, unknown>) => void) => windowEvents.set(name, callback)),
    removeEventListener: vi.fn((name: string) => windowEvents.delete(name)),
  };
  vi.stubGlobal("HTMLElement", ElementStub);
  vi.stubGlobal("document", browserDocument);
  vi.stubGlobal("window", browserWindow);
  lifecycle.active = true;
  const onClose = vi.fn();
  function render() {
    lifecycle.cursor = 0;
    const tree = MediaViewer({ asset, alt, onClose, opener: explicitOpener ? opener as unknown as HTMLElement : undefined });
    for (const node of nodes(tree)) {
      const ref = (node as unknown as { ref?: { current: unknown } }).ref;
      if (ref) ref.current = node.props.role === "dialog" ? viewer : close;
    }
    lifecycle.pending.splice(0).forEach((effect) => effect());
    return tree;
  }
  const tree = render();
  function request() {
    const button = nodes(tree).find((node) => node.type === "button" && node.props.children === "Toàn màn hình trình duyệt");
    if (!button) throw new Error("Missing browser fullscreen button");
    (button.props.onClick as () => void)();
  }
  return { tree, render, request, viewer, close, fullscreenButton, videoElement, opener, incidentalFocus, background, alreadyInert, browserDocument, browserWindow, onClose, windowEvents, documentEvents };
}

const image: Asset = { id: "image-result", mime: "image/png" };
const video: Asset = { id: "video-result", mime: "video/mp4" };

describe("per-asset fullscreen entry (requirements fullscreen addition 2026-10-08)", () => {
  it.each([
    { asset: image, label: "Xem ảnh toàn màn hình", tag: "img" },
    { asset: video, label: "Xem video toàn màn hình", tag: "video" },
  ])("renders a native fullscreen button for $tag", ({ asset, label, tag }) => {
    const html = renderToStaticMarkup(<AssetView asset={asset} alt="Kết quả" />);
    const buttons = html.match(/<button\b[^>]*>/g) ?? [];
    const openButton = buttons.filter((button) => button.includes(`aria-label="${label}"`));
    expect(openButton).toHaveLength(1);
    expect(openButton[0]).toContain('type="button"');
    expect(openButton[0]).not.toContain("disabled=");
    expect(html).toContain(`<${tag} `);
    expect(html).not.toContain('role="dialog"');
  });

  it.each([image, video])("uses the original cookie-authenticated asset URL for $mime", (asset) => {
    const html = renderToStaticMarkup(<AssetView asset={asset} alt="Kết quả" />);
    expect(html).toContain(`src="/api/assets/${asset.id}"`);
    expect(html).not.toMatch(/(?:token|api[_-]?key|access_token)=/i);
    expect(html).not.toContain("data:");
    expect(html).not.toContain("blob:");
    expect(html).not.toMatch(/\bautoplay(?:=|\s|>)/i);
  });

  it("encodes reserved characters in asset IDs without introducing a query token", () => {
    const asset: Asset = { id: "folder/result ?#&", mime: "image/jpeg" };
    const html = renderToStaticMarkup(<AssetView asset={asset} alt="Ảnh" />);
    expect(html).toContain('src="/api/assets/folder%2Fresult%20%3F%23%26"');
  });

  it("preserves default inline video controls and metadata-only loading", () => {
    const html = renderToStaticMarkup(<AssetView asset={video} alt="Video" />);
    const media = html.match(/<video\b[^>]*>/)?.[0];
    expect(media).toBeDefined();
    expect(media).toContain('controls=""');
    expect(media).toContain('preload="metadata"');
    expect(media).toContain('playsinline=""');
    expect(media).not.toMatch(/\bautoplay/i);
    expect(html).not.toMatch(/<button\b[^>]*>[\s\S]*<video\b/);
  });

  it("allows inline video controls to be disabled without hiding the fullscreen button", () => {
    const html = renderToStaticMarkup(<AssetView asset={video} alt="Video" controls={false} />);
    expect(html.match(/<video\b[^>]*>/)?.[0]).not.toContain("controls=");
    expect(html).toContain('aria-label="Xem video toàn màn hình"');
  });

  it("preserves image alternative text and default lazy loading", () => {
    const html = renderToStaticMarkup(<AssetView asset={image} alt={'Ảnh "gốc" <không cắt>'} />);
    expect(html).toContain('alt="Ảnh &quot;gốc&quot; &lt;không cắt&gt;"');
    expect(html).toContain('loading="lazy"');
    expect(html).not.toContain("<video");
  });

  it("supports eager comparison images and empty decorative alt text", () => {
    const html = renderToStaticMarkup(<AssetView asset={image} alt="" lazy={false} />);
    expect(html).toContain('alt=""');
    expect(html).not.toContain("loading=");
    expect(html).toContain('aria-label="Xem ảnh toàn màn hình"');
  });

  it("provides independent entry buttons for every result in a multi-asset group", () => {
    const html = renderToStaticMarkup(<>
      <AssetView asset={image} alt="Ảnh thứ nhất" />
      <AssetView asset={{ ...image, id: "second-image" }} alt="Ảnh thứ hai" />
      <AssetView asset={video} alt="Video thứ ba" />
    </>);
    expect(html.match(/aria-label="Xem ảnh toàn màn hình"/g)).toHaveLength(2);
    expect(html.match(/aria-label="Xem video toàn màn hình"/g)).toHaveLength(1);
    for (const id of [image.id, "second-image", video.id]) expect(html).toContain(`src="/api/assets/${id}"`);
  });
});

describe("portal viewer server-rendering safety", () => {
  it.each([
    { asset: image, alt: "Ảnh toàn màn hình" },
    { asset: video, alt: "Video toàn màn hình" },
    { asset: image, alt: "" },
  ])("does not require browser globals or call onClose while rendering $asset.mime / $alt", ({ asset, alt }) => {
    const onClose = vi.fn();
    expect(() => renderToStaticMarkup(<MediaViewer asset={asset} alt={alt} onClose={onClose} />)).not.toThrow();
    expect(onClose).not.toHaveBeenCalled();
  });
});

describe("viewer lifecycle with shallow hooks and browser boundary stubs", () => {
  it("includes controlled video in keyboard order without wrapping at the close button", () => {
    const mounted = mountViewer(video);
    const media = nodes(mounted.tree).find((node) => node.type === "video");
    expect(media?.props.tabIndex).toBe(0);
    const preventDefault = vi.fn();
    mounted.windowEvents.get("keydown")?.({ key: "Tab", shiftKey: false, preventDefault });
    expect(preventDefault).not.toHaveBeenCalled();
    mounted.videoElement.focus();
    mounted.windowEvents.get("keydown")?.({ key: "Tab", shiftKey: false, preventDefault });
    expect(mounted.browserDocument.activeElement).toBe(mounted.fullscreenButton);
    mounted.windowEvents.get("keydown")?.({ key: "Tab", shiftKey: true, preventDefault });
    expect(mounted.browserDocument.activeElement).toBe(mounted.videoElement);
    expect(preventDefault).toHaveBeenCalledTimes(2);
  });

  it("restores explicit opener instead of incidental focus at mount", () => {
    const mounted = mountViewer(image, "Kết quả", true);
    teardown();
    expect(mounted.browserDocument.activeElement).toBe(mounted.opener);
    expect(mounted.incidentalFocus.focus).not.toHaveBeenCalled();
  });

  it("does not focus a removed explicit opener or substitute incidental focus", () => {
    const mounted = mountViewer(image, "Kết quả", true);
    mounted.opener.isConnected = false;
    teardown();
    expect(mounted.opener.focus).not.toHaveBeenCalled();
    expect(mounted.incidentalFocus.focus).not.toHaveBeenCalled();
  });

  it("owns descendant video fullscreen, closes on its exit, and exits it on cleanup", () => {
    const mounted = mountViewer(video);
    mounted.browserDocument.fullscreenElement = mounted.videoElement;
    mounted.documentEvents.get("fullscreenchange")?.({});
    expect(mounted.onClose).not.toHaveBeenCalled();
    mounted.browserDocument.fullscreenElement = null;
    mounted.documentEvents.get("fullscreenchange")?.({});
    expect(mounted.onClose).toHaveBeenCalledOnce();
    mounted.browserDocument.fullscreenElement = mounted.videoElement;
    teardown();
    expect(mounted.browserDocument.exitFullscreen).toHaveBeenCalledOnce();
  });

  it("cleans up descendant fullscreen acquired after unmount", async () => {
    const mounted = mountViewer(video);
    let resolveRequest: () => void = () => {};
    mounted.viewer.requestFullscreen = vi.fn(() => new Promise<void>((resolve) => { resolveRequest = resolve; }));
    mounted.request();
    teardown();
    mounted.viewer.isConnected = false;
    mounted.browserDocument.fullscreenElement = mounted.videoElement;
    resolveRequest();
    await Promise.resolve();
    expect(mounted.browserDocument.exitFullscreen).toHaveBeenCalledOnce();
  });

  it.each([image, video])("renders accessible dialog and original $mime media without autoplay", (asset) => {
    const mounted = mountViewer(asset, "");
    const dialog = nodes(mounted.tree).find((node) => node.props.role === "dialog");
    expect(dialog?.props["aria-modal"]).toBe("true");
    expect(dialog?.props["aria-label"]).toBe("Xem media toàn màn hình");
    const media = nodes(mounted.tree).find((node) => node.type === (asset === image ? "img" : "video"));
    expect(media?.props.src).toBe(`/api/assets/${asset.id}`);
    expect(media?.props.autoPlay).toBeUndefined();
    if (asset === video) expect(media?.props.controls).toBe(true);
    const close = nodes(mounted.tree).find((node) => node.props["aria-label"] === "Đóng trình xem");
    (close?.props.onClick as () => void)();
    expect(mounted.onClose).toHaveBeenCalledOnce();
  });

  it("focuses close, locks background and restores inert, scroll, focus and listeners", () => {
    const mounted = mountViewer();
    expect(mounted.browserDocument.activeElement).toBe(mounted.close);
    expect(mounted.background.inert).toBe(true);
    expect(mounted.viewer.inert).toBe(false);
    expect(mounted.browserDocument.body.style.overflow).toBe("hidden");
    teardown();
    expect(mounted.background.inert).toBe(false);
    expect(mounted.alreadyInert.inert).toBe(true);
    expect(mounted.browserDocument.body.style.overflow).toBe("scroll");
    expect(mounted.browserDocument.activeElement).toBe(mounted.opener);
    expect(mounted.windowEvents.size).toBe(0);
    expect(mounted.documentEvents.size).toBe(0);
    expect(mounted.browserDocument.exitFullscreen).not.toHaveBeenCalled();
  });

  it("Escape closes without propagating to background actions; Enter does not close", () => {
    const mounted = mountViewer();
    const event = { key: "Escape", preventDefault: vi.fn(), stopImmediatePropagation: vi.fn() };
    mounted.windowEvents.get("keydown")?.({ ...event, key: "Enter" });
    expect(mounted.onClose).not.toHaveBeenCalled();
    mounted.windowEvents.get("keydown")?.(event);
    expect(mounted.onClose).toHaveBeenCalledOnce();
    expect(event.preventDefault).toHaveBeenCalledOnce();
    expect(event.stopImmediatePropagation).toHaveBeenCalledOnce();
  });

  it("wraps Tab both ways and redirects escaped focus", () => {
    const mounted = mountViewer();
    const preventDefault = vi.fn();
    mounted.windowEvents.get("keydown")?.({ key: "Tab", shiftKey: false, preventDefault });
    expect(mounted.browserDocument.activeElement).toBe(mounted.fullscreenButton);
    mounted.windowEvents.get("keydown")?.({ key: "Tab", shiftKey: true, preventDefault });
    expect(mounted.browserDocument.activeElement).toBe(mounted.close);
    expect(preventDefault).toHaveBeenCalledTimes(2);
    mounted.browserDocument.activeElement = mounted.background;
    mounted.documentEvents.get("focusin")?.({ target: mounted.background });
    expect(mounted.browserDocument.activeElement).toBe(mounted.close);
  });

  it("does not restore focus to a disconnected opener", () => {
    const mounted = mountViewer();
    mounted.opener.isConnected = false;
    teardown();
    expect(mounted.opener.focus).not.toHaveBeenCalled();
  });

  it("requests fullscreen only on explicit click and suppresses pending duplicates", async () => {
    const mounted = mountViewer();
    let resolveRequest: () => void = () => {};
    mounted.viewer.requestFullscreen = vi.fn(() => new Promise<void>((resolve) => { resolveRequest = resolve; }));
    expect(mounted.viewer.requestFullscreen).not.toHaveBeenCalled();
    mounted.request();
    mounted.request();
    expect(mounted.viewer.requestFullscreen).toHaveBeenCalledOnce();
    resolveRequest();
    await Promise.resolve();
    expect(mounted.onClose).not.toHaveBeenCalled();
  });

  it.each(["missing API", "rejected API", "other owner"])("retains viewport dialog and announces fallback: %s", async (scenario) => {
    const mounted = mountViewer();
    const request = vi.fn(async () => { throw new Error("Permission denied"); });
    mounted.viewer.requestFullscreen = scenario === "missing API" ? undefined : request;
    if (scenario === "other owner") mounted.browserDocument.fullscreenElement = mounted.background;
    mounted.request();
    await Promise.resolve();
    const tree = mounted.render();
    expect(nodes(tree).some((node) => node.props.role === "dialog")).toBe(true);
    expect(nodes(tree).find((node) => node.props.role === "status")?.props.children).toEqual(expect.any(String));
    expect(mounted.onClose).not.toHaveBeenCalled();
    if (scenario !== "rejected API") expect(request).not.toHaveBeenCalled();
    teardown();
    expect(mounted.browserDocument.exitFullscreen).not.toHaveBeenCalled();
  });

  it("closes on browser fullscreen exit only after ownership, and exits owned fullscreen on cleanup", () => {
    const mounted = mountViewer();
    mounted.documentEvents.get("fullscreenchange")?.({});
    expect(mounted.onClose).not.toHaveBeenCalled();
    mounted.browserDocument.fullscreenElement = mounted.viewer;
    mounted.documentEvents.get("fullscreenchange")?.({});
    mounted.browserDocument.fullscreenElement = null;
    mounted.documentEvents.get("fullscreenchange")?.({});
    expect(mounted.onClose).toHaveBeenCalledOnce();
    mounted.browserDocument.fullscreenElement = mounted.viewer;
    teardown();
    expect(mounted.browserDocument.exitFullscreen).toHaveBeenCalledOnce();
  });

  it("cleans fullscreen acquired after unmount", async () => {
    const mounted = mountViewer();
    let resolveRequest: () => void = () => {};
    mounted.viewer.requestFullscreen = vi.fn(() => new Promise<void>((resolve) => { resolveRequest = resolve; }));
    mounted.request();
    teardown();
    mounted.viewer.isConnected = false;
    mounted.browserDocument.fullscreenElement = mounted.viewer;
    resolveRequest();
    await Promise.resolve();
    expect(mounted.browserDocument.exitFullscreen).toHaveBeenCalledOnce();
  });
});
