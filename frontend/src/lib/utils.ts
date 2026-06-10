import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/**
 * Rewrite a RustFS internal URL (http://rustfs:9000/...) to a browser-accessible URL.
 * Falls back to the same-origin Next.js file proxy.
 */
export function resolveFileUrl(url: string): string {
  if (!url) return url;
  const publicBase =
    process.env.NEXT_PUBLIC_FILES_URL ?? "/files/liveos-assets";
  // Replace the internal Docker hostname+port+bucket prefix with the public base
  return url.replace(/https?:\/\/rustfs:\d+\/[^/]+/, publicBase);
}

/** Returns true if the URL points to an image file. */
export function isImageUrl(url: string): boolean {
  return /\.(jpg|jpeg|png|gif|webp|svg)(\?|$)/i.test(url);
}

/** Returns true if the URL points to a video file. */
export function isVideoUrl(url: string): boolean {
  return /\.(mp4|webm|ogg|mov)(\?|$)/i.test(url);
}
