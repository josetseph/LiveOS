/** Pick the best supported MediaRecorder MIME type for the current browser. */
export function pickSupportedAudioMimeType(): string {
  // Safari only supports MP4/AAC; Chrome/Firefox support WebM/Opus.
  const preferredTypes = [
    "audio/mp4;codecs=aac", // Safari
    "audio/mp4", // Safari fallback
    "audio/webm;codecs=opus", // Chrome / Firefox
    "audio/webm", // Chrome / Firefox fallback
  ];
  return preferredTypes.find((t) => MediaRecorder.isTypeSupported(t)) ?? "";
}
