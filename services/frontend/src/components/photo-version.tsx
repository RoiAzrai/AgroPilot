"use client";

import { createContext, useContext, useState, type ReactNode } from "react";

type PhotoVersion = { version: number | null; setVersion: (v: number) => void };

const Ctx = createContext<PhotoVersion>({ version: null, setVersion: () => {} });

// Plot page: the photo card sets a new version after an upload, and every image of that
// plot (card and phone thumbnail) adds it to its URL so the browser loads the new photo.
export function PhotoVersionProvider({ children }: { children: ReactNode }) {
  const [version, setVersion] = useState<number | null>(null);
  return <Ctx value={{ version, setVersion }}>{children}</Ctx>;
}

export const usePhotoVersion = () => useContext(Ctx);
