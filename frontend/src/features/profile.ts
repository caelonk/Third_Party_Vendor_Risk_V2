import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { SignInEvent, User } from "@/lib/types";

export const MAX_NAME_LENGTH = 200;
export const AVATAR_TYPES = ["image/png", "image/jpeg", "image/webp"];
/** What the server accepts. Photos are resized in the browser first, so this is
 *  only reached if that step is unavailable. */
export const MAX_UPLOAD_BYTES = 5 * 1024 * 1024;
/** The largest original we will try to resize in the browser. */
export const MAX_SOURCE_BYTES = 25 * 1024 * 1024;
const UPLOAD_SIDE = 512; // px; the server stores 256, so this leaves headroom

const mb = (bytes: number) => Math.round(bytes / (1024 * 1024));

/** Why a chosen file can't be used as a photo, or null if it can. */
export function avatarFileProblem(file: { type: string; size: number }): string | null {
  if (!AVATAR_TYPES.includes(file.type)) return "Choose a PNG, JPEG or WebP image.";
  if (file.size > MAX_SOURCE_BYTES) return `That image is larger than ${mb(MAX_SOURCE_BYTES)} MB.`;
  return null;
}

/**
 * Crop a chosen photo to a centred square and shrink it before uploading, so a
 * 12 MB phone photo becomes a few hundred KB. The server validates and
 * re-encodes whatever arrives, so this is for speed, not safety; if the browser
 * can't do it the original is sent as long as it is within the upload limit.
 */
export async function prepareAvatar(file: File): Promise<Blob> {
  const problem = avatarFileProblem(file);
  if (problem) throw new Error(problem);
  try {
    const bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
    const side = Math.min(bitmap.width, bitmap.height);
    const size = Math.min(UPLOAD_SIDE, side);
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = size;
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("no canvas");
    ctx.imageSmoothingQuality = "high";
    ctx.drawImage(
      bitmap,
      (bitmap.width - side) / 2,
      (bitmap.height - side) / 2,
      side,
      side,
      0,
      0,
      size,
      size,
    );
    bitmap.close();
    const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/png"));
    if (blob) return blob;
  } catch {
    // Fall through to sending the original.
  }
  if (file.size > MAX_UPLOAD_BYTES) {
    throw new Error(`That image is larger than ${mb(MAX_UPLOAD_BYTES)} MB. Choose a smaller one.`);
  }
  return file;
}

const METHOD_LABELS: Record<string, string> = { password: "Password", google: "Google" };

export function signInMethodLabel(method: string): string {
  return METHOD_LABELS[method] ?? method.charAt(0).toUpperCase() + method.slice(1);
}

// Order matters: Edge and Opera also say "Chrome", and Chrome also says "Safari".
const BROWSERS: [RegExp, string][] = [
  [/\bEdg(?:e|A|iOS)?\//, "Edge"],
  [/\bOPR\/|\bOpera\b/, "Opera"],
  [/\bFirefox\/|\bFxiOS\//, "Firefox"],
  [/\bChrome\/|\bCriOS\//, "Chrome"],
  [/\bSafari\//, "Safari"],
];
// Order matters: iPhones and iPads mention "Mac OS X", Android mentions "Linux".
const SYSTEMS: [RegExp, string][] = [
  [/\biPhone\b|\biPod\b/, "iPhone"],
  [/\biPad\b/, "iPad"],
  [/\bAndroid\b/, "Android"],
  [/\bWindows\b/, "Windows"],
  [/\bMac OS X\b|\bMacintosh\b/, "macOS"],
  [/\bCrOS\b/, "ChromeOS"],
  [/\bLinux\b/, "Linux"],
];

/**
 * A short, human description of a browser from its user-agent string, e.g.
 * "Chrome on Windows". Deliberately coarse: enough to recognise your own
 * devices. Says "Unknown device" rather than guessing.
 */
export function describeBrowser(userAgent: string | null): string {
  if (!userAgent) return "Unknown device";
  const browser = BROWSERS.find(([re]) => re.test(userAgent))?.[1];
  const system = SYSTEMS.find(([re]) => re.test(userAgent))?.[1];
  if (browser && system) return `${browser} on ${system}`;
  return browser ?? system ?? "Unknown device";
}

export function fmtDateTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

const LOGINS_KEY = ["recent-sign-ins"];

export function useRecentSignIns() {
  return useQuery({
    queryKey: LOGINS_KEY,
    queryFn: () => api.get<SignInEvent[]>("/me/logins"),
  });
}

export function useUpdateProfile(onSaved: (user: User) => void) {
  return useMutation({
    mutationFn: (name: string) => api.patch<User>("/me", { name }),
    onSuccess: onSaved,
  });
}

export function useUploadAvatar(onSaved: (user: User) => void) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (file: File) => api.put<User>("/me/avatar", await prepareAvatar(file)),
    onSuccess: (user) => {
      onSaved(user);
      void qc.invalidateQueries({ queryKey: ["members"] }); // the photo shows in member lists
    },
  });
}

export function useRemoveAvatar(onSaved: (user: User) => void) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.del<User>("/me/avatar"),
    onSuccess: (user) => {
      onSaved(user);
      void qc.invalidateQueries({ queryKey: ["members"] });
    },
  });
}
