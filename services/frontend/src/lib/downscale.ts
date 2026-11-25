// Browser only (canvas, createImageBitmap). Not unit tested: the size math it uses
// is scaledSize in photo.ts, which is.
import { scaledSize } from "./photo";

type Source = { image: CanvasImageSource; width: number; height: number; done: () => void };

// Upright decode: createImageBitmap with the EXIF orientation applied; older browsers
// fall back to an <img>, which applies EXIF orientation itself when drawn.
async function decode(file: Blob): Promise<Source> {
  if (typeof createImageBitmap === "function") {
    try {
      const bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
      return { image: bitmap, width: bitmap.width, height: bitmap.height, done: () => bitmap.close() };
    } catch {
      // fall through to the <img> path
    }
  }
  const url = URL.createObjectURL(file);
  try {
    const img = new Image();
    img.src = url;
    await img.decode();
    return {
      image: img,
      width: img.naturalWidth,
      height: img.naturalHeight,
      done: () => URL.revokeObjectURL(url),
    };
  } catch (e) {
    URL.revokeObjectURL(url);
    throw e;
  }
}

// Re-encodes the photo as JPEG (quality 0.85), long side at most 2048 px, on a white
// background (PNG transparency would turn black). Re-encoding drops EXIF, GPS included.
// Returns null when the browser cannot decode or encode the file.
export async function downscaleToJpeg(file: Blob): Promise<Blob | null> {
  let source: Source;
  try {
    source = await decode(file);
  } catch {
    return null;
  }
  try {
    if (source.width === 0 || source.height === 0) return null;
    const { width, height } = scaledSize(source.width, source.height);
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext("2d");
    if (!ctx) return null;
    ctx.fillStyle = "#FFFFFF";
    ctx.fillRect(0, 0, width, height);
    ctx.drawImage(source.image, 0, 0, width, height);
    return await new Promise<Blob | null>((resolve) =>
      canvas.toBlob(resolve, "image/jpeg", 0.85),
    );
  } finally {
    source.done();
  }
}
