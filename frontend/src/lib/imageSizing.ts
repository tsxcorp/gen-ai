import type { Asset, Manifest, ParamDef, Params, Scalar } from "../api/types";
import { enumOptions, resolveConstraints, visibleParams } from "./constraints";

type SizeChoice = { value: string; exact: boolean };
type Dimensions = { width: number; height: number };

export function validDimensions(width: number, height: number): boolean {
  return Number.isFinite(width) && Number.isFinite(height) && width > 0 && height > 0;
}

export function numericRatio(value: string): number | null {
  const match = /^(\d+(?:\.\d+)?):(\d+(?:\.\d+)?)$/.exec(value);
  if (!match) return null;
  const width = Number(match[1]);
  const height = Number(match[2]);
  return validDimensions(width, height) ? width / height : null;
}

export function chooseAspectRatio(width: number, height: number, values: Scalar[]): SizeChoice | null {
  if (!validDimensions(width, height)) return null;
  const source = width / height;
  let best: SizeChoice | null = null;
  let bestError = Infinity;
  for (const value of values) {
    const candidate = typeof value === "string" ? numericRatio(value) : null;
    if (candidate === null) continue;
    const error = Math.abs(Math.log(candidate / source));
    if (error < bestError - 1e-12) {
      bestError = error;
      best = { value: String(value), exact: error < 1e-10 };
    }
  }
  return best;
}

function validSizeRule(param: ParamDef): boolean {
  const rule = param.sizeRule;
  if (!rule || !rule.maxEdge) return false;
  if (Object.entries(rule).some(([key, value]) => key !== "allow" && (typeof value !== "number" || !Number.isFinite(value) || value <= 0))) return false;
  const step = rule.multipleOf ?? 1;
  return Number.isSafeInteger(step) && Number.isSafeInteger(rule.maxEdge) &&
    Math.floor(rule.maxEdge / step) <= 65536 && (rule.maxRatio ?? 1) >= 1 &&
    (rule.minPixels ?? 0) <= (rule.maxPixels ?? Infinity);
}

export function validImageSize(value: string, param: ParamDef): boolean {
  if (!validSizeRule(param)) return false;
  const match = /^(\d+)x(\d+)$/.exec(value);
  if (!match) return false;
  const width = Number(match[1]);
  const height = Number(match[2]);
  const rule = param.sizeRule as NonNullable<ParamDef["sizeRule"]>;
  const step = rule.multipleOf ?? 1;
  return validDimensions(width, height) && width % step === 0 && height % step === 0 &&
    Math.max(width, height) <= (rule.maxEdge as number) &&
    Math.max(width / height, height / width) <= (rule.maxRatio ?? Infinity) &&
    width * height >= (rule.minPixels ?? 0) && width * height <= (rule.maxPixels ?? Infinity);
}

export function chooseImageSize(width: number, height: number, param: ParamDef, allowed?: Scalar[]): SizeChoice | null {
  const rule = param.sizeRule;
  if (!validDimensions(width, height) || !rule || !validSizeRule(param)) return null;
  const step = rule.multipleOf ?? 1;
  const maxEdge = rule.maxEdge as number;
  const ratio = width / height;
  const defaultSize = /^(\d+)x(\d+)$/.exec(String(param.default ?? ""));
  const defaultArea = defaultSize ? Number(defaultSize[1]) * Number(defaultSize[2]) : 0;
  const targetArea = defaultArea > 0 && Number.isFinite(defaultArea) ? defaultArea : width * height;
  let best: SizeChoice | null = null;
  let bestRatioError = Infinity;
  let bestAreaError = Infinity;
  const consider = (candidateWidth: number, candidateHeight: number) => {
      if (!validImageSize(`${candidateWidth}x${candidateHeight}`, param)) return;
      const ratioError = Math.abs(Math.log((candidateWidth / candidateHeight) / ratio));
      const areaError = Math.abs(Math.log((candidateWidth * candidateHeight) / targetArea));
      if (ratioError < bestRatioError - 1e-12 || (Math.abs(ratioError - bestRatioError) <= 1e-12 && areaError < bestAreaError - 1e-12)) {
        bestRatioError = ratioError;
        bestAreaError = areaError;
        best = { value: `${candidateWidth}x${candidateHeight}`, exact: ratioError < 1e-10 };
      }
  };
  if (allowed) {
    const sizes = allowed.filter((value): value is string => typeof value === "string" && validImageSize(value, param))
      .map((value) => value.split("x").map(Number) as [number, number])
      .sort((first, second) => first[0] - second[0] || first[1] - second[1]);
    for (const [candidateWidth, candidateHeight] of sizes) consider(candidateWidth, candidateHeight);
  } else {
    const maxRatio = rule.maxRatio ?? Infinity;
    for (let candidateWidth = step; candidateWidth <= maxEdge; candidateWidth += step) {
      const minHeight = Math.ceil(Math.max(step, (rule.minPixels ?? 0) / candidateWidth, candidateWidth / maxRatio) / step) * step;
      const maxHeight = Math.floor(Math.min(maxEdge, (rule.maxPixels ?? Infinity) / candidateWidth, candidateWidth * maxRatio) / step) * step;
      if (minHeight > maxHeight) continue;
      const ideal = Math.min(maxHeight, Math.max(minHeight, candidateWidth / ratio));
      const lower = Math.max(minHeight, Math.floor(ideal / step) * step);
      const upper = Math.min(maxHeight, Math.ceil(ideal / step) * step);
      consider(candidateWidth, lower);
      if (upper !== lower) consider(candidateWidth, upper);
    }
  }
  return best;
}

export function imageSizingParam(manifest: Manifest, mode: string): ParamDef | undefined {
  if (manifest.kind !== "image" || mode !== "edit") return undefined;
  return visibleParams(manifest, mode).find((param) =>
    param.type === "ratio" || param.key === "aspect_ratio",
  ) ?? visibleParams(manifest, mode).find((param) => param.key === "size" && !!param.sizeRule);
}

export function firstReference(manifest: Manifest, mode: string, slots: Record<string, Asset | Asset[]>): Asset | undefined {
  for (const param of visibleParams(manifest, mode)) {
    if (param.type !== "image" && param.type !== "imageList") continue;
    const assets = slots[param.key];
    const first = Array.isArray(assets) ? assets[0] : assets;
    if (first) return first;
  }
  return undefined;
}

export interface ImageSizing {
  params: Params;
  key?: string;
  value?: string;
  source?: Asset;
  error?: string;
  note?: string;
  approximate?: boolean;
}

export function resolveImageSizing(manifest: Manifest, mode: string, params: Params, slots: Record<string, Asset | Asset[]>, auto: boolean): ImageSizing {
  const param = imageSizingParam(manifest, mode);
  if (!param || !auto) return { params };
  const source = firstReference(manifest, mode, slots);
  const base = { params, key: param.key, source };
  if (!source) return { ...base, error: "Auto cần ảnh gốc. Tải ảnh lên và xác nhận quyền sử dụng, hoặc chọn kích thước thủ công." };
  if (!validDimensions(source.width ?? 0, source.height ?? 0)) {
    return { ...base, error: "Chưa đọc được kích thước ảnh gốc. Chờ ảnh tải xong hoặc chọn tỷ lệ/kích thước thủ công." };
  }
  const width = source.width as number;
  const height = source.height as number;
  const resolved = resolveConstraints(manifest, mode, params);
  let choice: SizeChoice | null;
  if (param.sizeRule) choice = chooseImageSize(width, height, param, resolved.allowed[param.key]);
  else choice = chooseAspectRatio(width, height, enumOptions(param, resolved.allowed));
  const initialForce = resolved.locked[param.key] ? resolved.effective[param.key] : undefined;
  if (typeof initialForce === "string") {
    const candidate = param.sizeRule ? validImageSize(initialForce, param) : param.values?.includes(initialForce) && numericRatio(initialForce) !== null;
    if (!candidate) return { ...base, error: "Luật model không có kích thước cụ thể hợp lệ cho Auto. Chọn thủ công." };
    const forcedRatio = param.sizeRule ? initialForce.split("x").map(Number) : initialForce.split(":").map(Number);
    choice = { value: initialForce, exact: Math.abs(Math.log(((forcedRatio[0] as number) / (forcedRatio[1] as number)) / (width / height))) < 1e-10 };
  }
  if (!choice) return { ...base, error: "Model không có kích thước hợp lệ cho Auto. Chọn kích thước thủ công." };
  let concrete = { ...params, [param.key]: choice.value };
  const checked = resolveConstraints(manifest, mode, concrete);
  const forced = checked.locked[param.key];
  if (checked.effective[param.key] !== choice.value) {
    const value = checked.effective[param.key];
    if (typeof value !== "string" || (param.sizeRule ? !validImageSize(value, param) : !param.values?.includes(value) || numericRatio(value) === null)) {
      return { ...base, error: "Luật model không cho phép Auto ở cấu hình này." };
    }
    concrete = { ...concrete, [param.key]: value };
    const parts = value.split(param.sizeRule ? "x" : ":").map(Number);
    choice = { value, exact: Math.abs(Math.log(((parts[0] as number) / (parts[1] as number)) / (width / height))) < 1e-10 };
  }
  if (checked.errorItems.some((error) => error.key === param.key)) {
    return { ...base, error: "Tỷ lệ Auto không hợp lệ với cấu hình model hiện tại. Chọn thủ công." };
  }
  const approximate = !choice.exact;
  const note = `Ảnh gốc ${width} × ${height} → ${choice.value}. ${forced ? `Model áp dụng luật: ${forced}` : approximate ? "Model không hỗ trợ đúng tỷ lệ gốc; dùng tỷ lệ hợp lệ gần nhất." : "Giữ tỷ lệ ảnh gốc."} Ảnh đầu tiên làm nguồn.`;
  return { params: concrete, key: param.key, value: choice.value, source, note, approximate };
}

export function readImageDimensions(src: string): Promise<Dimensions> {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => {
      if (validDimensions(image.naturalWidth, image.naturalHeight)) resolve({ width: image.naturalWidth, height: image.naturalHeight });
      else reject(new Error("Không đọc được kích thước ảnh"));
    };
    image.onerror = () => reject(new Error("Trình duyệt không đọc được định dạng ảnh này"));
    image.src = src;
  });
}
