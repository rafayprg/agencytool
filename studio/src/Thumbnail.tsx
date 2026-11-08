import React from "react";
import { AbsoluteFill, Img, staticFile } from "remotion";
import { DEFAULT_THEME, Theme } from "./Tutorial";

export type ThumbnailProps = {
  theme?: Theme;
  text: string;
  badge: string;
  phoneImage: string; // file in the public dir
  phone: { w: number; h: number };
};

const isLight = (hex: string): boolean => {
  const n = parseInt(hex.replace("#", ""), 16);
  return 0.299 * ((n >> 16) & 255) + 0.587 * ((n >> 8) & 255) + 0.114 * (n & 255) > 150;
};

/** Huge text that still fits the text column: limited by the longest word and by line count. */
const hookSize = (text: string, columnWidth: number): number => {
  const words = text.split(/\s+/).filter(Boolean);
  const longestWord = Math.max(...words.map((w) => w.length), 1);
  const byWord = Math.floor(columnWidth / (longestWord * 0.72)); // heavy caps are ~0.7em wide
  const byLength = text.length <= 14 ? 132 : text.length <= 24 ? 112 : text.length <= 36 ? 92 : 76;
  return Math.max(48, Math.min(byWord, byLength));
};

export const Thumbnail: React.FC<ThumbnailProps> = ({ theme = DEFAULT_THEME, text, badge, phoneImage, phone }) => {
  const c = theme.colors;
  const light = isLight(c.bg1);
  const phoneH = 640;
  const phoneW = Math.min((phoneH * phone.w) / phone.h, 420);
  const bezel = 12;
  const words = text.split(/\s+/).filter(Boolean);
  const highlight = words.length > 1 ? words.length - 1 : -1; // last word in the accent colour
  const columnWidth = 1280 - 64 - phoneW - 2 * bezel - 120;
  return (
    <AbsoluteFill style={{ background: `radial-gradient(circle at 70% 40%, ${c.bg2} 0%, ${c.bg1} 70%)`, fontFamily: theme.font }}>
      {theme.grid && (
        <AbsoluteFill
          style={{
            backgroundImage: `linear-gradient(${light ? "rgba(0,0,0,0.05)" : "rgba(255,255,255,0.05)"} 1px, transparent 1px), linear-gradient(90deg, ${light ? "rgba(0,0,0,0.05)" : "rgba(255,255,255,0.05)"} 1px, transparent 1px)`,
            backgroundSize: "48px 48px",
          }}
        />
      )}
      <div
        style={{
          position: "absolute",
          left: 64,
          top: 70,
          width: columnWidth,
          display: "flex",
          flexDirection: "column",
          gap: 28,
        }}
      >
        <div
          style={{
            alignSelf: "flex-start",
            background: c.accent2,
            color: isLight(c.accent2) ? "#0a0f1f" : "#ffffff",
            fontWeight: 900,
            fontSize: 34,
            letterSpacing: 3,
            padding: "10px 22px",
            borderRadius: 14,
            transform: "rotate(-2deg)",
          }}
        >
          {badge}
        </div>
        <div
          style={{
            fontWeight: 900,
            fontSize: hookSize(text, columnWidth),
            lineHeight: 1.0,
            color: c.text,
            textTransform: "uppercase",
            textShadow: light ? "0 4px 0 rgba(0,0,0,0.08)" : "0 6px 0 rgba(0,0,0,0.45)",
            display: "flex",
            flexWrap: "wrap",
            columnGap: 22,
            rowGap: 4,
          }}
        >
          {words.map((w, i) => (
            <span key={i} style={{ color: i === highlight ? c.accent : c.text }}>
              {w}
            </span>
          ))}
        </div>
      </div>
      <div
        style={{
          position: "absolute",
          right: 90,
          top: (720 - phoneH) / 2 - bezel,
          padding: bezel,
          borderRadius: 52,
          background: "linear-gradient(145deg,#2b2f3a,#0d0f14)",
          boxShadow: `0 30px 70px rgba(0,0,0,0.5), 0 0 0 6px ${c.accent}`,
          transform: "rotate(4deg)",
        }}
      >
        <div style={{ width: phoneW, height: phoneH, borderRadius: 42, overflow: "hidden", background: "#fff" }}>
          <Img src={staticFile(phoneImage)} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
        </div>
      </div>
    </AbsoluteFill>
  );
};
