import React from "react";
import {
  AbsoluteFill,
  Audio,
  interpolate,
  OffthreadVideo,
  Sequence,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
type Word = { w: string; s: number; e: number };
export type Scene = {
  id: number;
  src: number[];
  chapter: string;
  sub: string;
  callout: string;
  text: string;
  audio: string;
  from: number;
  frames: number;
  words: Word[];
};
export type Timeline = {
  title: string;
  fps: number;
  total: number;
  phone?: { w: number; h: number };
  labels?: { tap: string };
  scenes: Scene[];
};
export type Theme = {
  name: string;
  colors: { bg1: string; bg2: string; accent: string; accent2: string; text: string };
  font: string;
  captionScale: number;
  layout: "phone-right" | "phone-left";
  grid: boolean;
  music: boolean;
  musicVolume: number;
};
export type TutorialProps = { vertical: boolean; timeline: Timeline; theme?: Theme };

export const DEFAULT_THEME: Theme = {
  name: "Neon Night",
  colors: { bg1: "#0a0f1f", bg2: "#1b1446", accent: "#ffd23f", accent2: "#5b8cff", text: "#ffffff" },
  font: "'Segoe UI', 'Helvetica Neue', Arial, sans-serif",
  captionScale: 1,
  layout: "phone-right",
  grid: true,
  music: true,
  musicVolume: 0.07,
};
const ThemeCtx = React.createContext<Theme>(DEFAULT_THEME);
/** Palette used by every component; `muted`/`panel` adapt to light or dark backgrounds. */
const usePalette = () => {
  const t = React.useContext(ThemeCtx);
  const light = isLight(t.colors.bg1);
  return {
    ...t.colors,
    font: t.font,
    captionScale: t.captionScale,
    grid: t.grid,
    line: light ? "rgba(0,0,0,0.05)" : "rgba(255,255,255,0.035)",
    panel: light ? "rgba(255,255,255,0.92)" : "rgba(10,15,31,0.85)",
    shadow: light ? "0 4px 18px rgba(255,255,255,0.9)" : "0 4px 18px rgba(0,0,0,0.8)",
    onAccent: isLight(t.colors.accent) ? "#0a0f1f" : "#ffffff",
    onAccent2: isLight(t.colors.accent2) ? "#0a0f1f" : "#ffffff",
  };
};
const isLight = (hex: string): boolean => {
  const n = parseInt(hex.replace("#", ""), 16);
  const r = (n >> 16) & 255, g = (n >> 8) & 255, b = n & 255;
  return 0.299 * r + 0.587 * g + 0.114 * b > 150;
};

const TimelineCtx = React.createContext<Timeline | null>(null);
const useTimeline = (): Timeline => {
  const t = React.useContext(TimelineCtx);
  if (!t) throw new Error("timeline missing");
  return t;
};

const DEFAULT_PHONE = { w: 460, h: 1044 };
const MAX_WORDS_PER_LINE = 5;
const MAX_CHARS_PER_LINE = 30; // long words (Spanish, German) would otherwise run off screen

/** Big heading shrinks for long text so it never collides with the phone or callout. */
const headingSize = (text: string, vertical: boolean): number => {
  const len = text.length;
  if (vertical) return len <= 22 ? 78 : len <= 40 ? 62 : 50;
  return len <= 28 ? 84 : len <= 50 ? 68 : 56;
};

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

/** Pick which part of the source window to show and how fast, so it fills the voice line. */
const videoWindow = (scene: Scene, fps: number) => {
  const [s0, s1] = scene.src;
  const outSec = scene.frames / fps;
  const rate = clamp((s1 - s0) / outSec, 0.6, 2.2);
  const used = rate * outSec;
  const start = s0 + Math.max(0, s1 - s0 - used) / 2;
  return { rate, trimBefore: Math.round(start * fps) };
};

/** Split words into short caption lines, breaking on punctuation. */
const chunkWords = (words: Word[]): Word[][] => {
  const lines: Word[][] = [];
  let cur: Word[] = [];
  const chars = (ws: Word[]) => ws.reduce((n, x) => n + x.w.length + 1, 0);
  for (const w of words) {
    if (cur.length && chars(cur) + w.w.length > MAX_CHARS_PER_LINE) {
      lines.push(cur);
      cur = [];
    }
    cur = [...cur, w];
    if (cur.length >= MAX_WORDS_PER_LINE || /[.,:!?¿¡]$/.test(w.w)) {
      lines.push(cur);
      cur = [];
    }
  }
  return cur.length ? [...lines, cur] : lines;
};

const Background: React.FC = () => {
  const C = usePalette();
  const frame = useCurrentFrame();
  const drift = Math.sin(frame / 90) * 6;
  return (
    <AbsoluteFill
      style={{
        background: `radial-gradient(circle at ${30 + drift}% 25%, ${C.bg2} 0%, ${C.bg1} 60%)`,
      }}
    >
      <AbsoluteFill
        style={{
          backgroundImage:
            C.grid
            ? `linear-gradient(${C.line} 1px, transparent 1px), linear-gradient(90deg, ${C.line} 1px, transparent 1px)`
            : "none",
          backgroundSize: "60px 60px",
        }}
      />
    </AbsoluteFill>
  );
};

const Phone: React.FC<{ scene: Scene; height: number }> = ({ scene, height }) => {
  const C = usePalette();
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const { rate, trimBefore } = videoWindow(scene, fps);
  const phone = useTimeline().phone ?? DEFAULT_PHONE;
  const width = (height * phone.w) / phone.h;
  const enter = spring({ frame, fps, config: { damping: 200 }, durationInFrames: 12 });
  const push = interpolate(frame, [0, scene.frames], [1, 1.035]);
  const bezel = height * 0.018;
  return (
    <div
      style={{
        width: width + bezel * 2,
        height: height + bezel * 2,
        padding: bezel,
        borderRadius: height * 0.075,
        background: "linear-gradient(145deg,#2b2f3a,#0d0f14)",
        boxShadow: `0 40px 90px rgba(0,0,0,0.55), 0 0 0 2px rgba(255,255,255,0.08), 0 0 80px ${C.accent2}33`,
        transform: `scale(${push * interpolate(enter, [0, 1], [0.97, 1])})`,
        opacity: interpolate(enter, [0, 1], [0.6, 1]),
      }}
    >
      <div style={{ width, height, borderRadius: height * 0.062, overflow: "hidden", background: "#fff" }}>
        <OffthreadVideo
          src={staticFile("phone.mp4")}
          trimBefore={trimBefore}
          playbackRate={rate}
          muted
          style={{ width: "100%", height: "100%", objectFit: "cover" }}
        />
      </div>
    </div>
  );
};

const Heading: React.FC<{ scene: Scene; vertical: boolean; isNewChapter: boolean }> = ({
  scene,
  vertical,
  isNewChapter,
}) => {
  const C = usePalette();
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const p = isNewChapter ? spring({ frame, fps, config: { damping: 18 } }) : 1;
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: vertical ? "center" : "flex-start", gap: 14 }}>
      <div
        style={{
          fontFamily: C.font,
          fontWeight: 800,
          fontSize: vertical ? 34 : 30,
          letterSpacing: 4,
          textTransform: "uppercase",
          color: C.onAccent,
          background: C.accent,
          padding: "8px 22px",
          borderRadius: 999,
          transform: `translateY(${(1 - p) * 30}px)`,
          opacity: p,
        }}
      >
        {scene.chapter}
      </div>
      <div
        style={{
          fontFamily: C.font,
          fontWeight: 900,
          fontSize: headingSize(scene.sub, vertical),
          lineHeight: 1.05,
          color: C.text,
          textAlign: vertical ? "center" : "left",
          maxWidth: vertical ? 980 : 860,
          display: "-webkit-box",
          WebkitLineClamp: 3,
          WebkitBoxOrient: "vertical",
          overflow: "hidden",
          transform: `translateY(${(1 - p) * 50}px)`,
          opacity: p,
        }}
      >
        {scene.sub}
      </div>
    </div>
  );
};

const Callout: React.FC<{ text: string; vertical: boolean }> = ({ text, vertical }) => {
  const C = usePalette();
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const p = spring({ frame: frame - 6, fps, config: { damping: 12, stiffness: 160 } });
  const tap = useTimeline().labels?.tap ?? "TAP";
  const pulse = 1 + Math.sin(Math.max(0, frame - 20) / 6) * 0.015;
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 18,
        transform: `scale(${p * pulse})`,
        transformOrigin: vertical ? "center" : "left center",
      }}
    >
      <div
        style={{
          fontFamily: C.font,
          fontWeight: 900,
          fontSize: vertical ? 30 : 28,
          color: C.onAccent2,
          background: C.accent2,
          padding: "10px 18px",
          borderRadius: 14,
          letterSpacing: 2,
        }}
      >
        👆 {tap}
      </div>
      <div
        style={{
          fontFamily: C.font,
          fontWeight: 800,
          fontSize: (vertical ? 50 : 48) * (text.length > 22 ? 0.8 : 1),
          maxWidth: vertical ? 760 : 820,
          color: C.text,
          padding: "12px 28px",
          borderRadius: 18,
          border: `5px solid ${C.accent}`,
          background: C.panel,
          boxShadow: `0 0 40px ${C.accent}55`,
        }}
      >
        {text}
      </div>
    </div>
  );
};

const Captions: React.FC<{ words: Word[]; vertical: boolean }> = ({ words, vertical }) => {
  const C = usePalette();
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = frame / fps;
  const lines = chunkWords(words);
  const line = lines.find((l) => t < l[l.length - 1].e + 0.15) ?? lines[lines.length - 1];
  if (!line || t > words[words.length - 1].e + 0.3) return null;
  return (
    <div
      style={{
        fontFamily: C.font,
        fontWeight: 900,
        fontSize: (vertical ? 64 : 54) * C.captionScale,
        lineHeight: 1.2,
        textAlign: vertical ? "center" : "left",
        textShadow: C.shadow,
        maxWidth: vertical ? 960 : 860,
        display: "flex",
        flexWrap: "wrap",
        justifyContent: vertical ? "center" : "flex-start",
        columnGap: 14,
      }}
    >
      {line.map((w, i) => {
        const active = t >= w.s;
        return (
          <span key={i} style={{ color: active ? C.accent : C.text, opacity: active ? 1 : 0.55 }}>
            {w.w}
          </span>
        );
      })}
    </div>
  );
};

const ProgressBar: React.FC = () => {
  const C = usePalette();
  const frame = useCurrentFrame();
  const pct = (frame / useTimeline().total) * 100;
  return (
    <div style={{ position: "absolute", left: 0, bottom: 0, height: 8, width: "100%", background: C.line }}>
      <div style={{ height: "100%", width: `${pct}%`, background: C.accent }} />
    </div>
  );
};

/** Phone height that fits the slot even for wide crops (tablets, landscape recordings). */
const usePhoneHeight = (maxH: number, maxW: number): number => {
  const phone = useTimeline().phone ?? DEFAULT_PHONE;
  return Math.min(maxH, (maxW * phone.h) / phone.w);
};

const SceneView: React.FC<{ scene: Scene; vertical: boolean; isNewChapter: boolean }> = ({
  scene,
  vertical,
  isNewChapter,
}) => {
  const { layout } = React.useContext(ThemeCtx);
  const words = scene.words;
  const wideH = usePhoneHeight(940, 760);
  const tallH = usePhoneHeight(960, 900);
  if (vertical) {
    return (
      <AbsoluteFill style={{ alignItems: "center" }}>
        <div style={{ position: "absolute", top: 110 }}>
          <Heading scene={scene} vertical isNewChapter={isNewChapter} />
        </div>
        <div style={{ position: "absolute", top: 360 + (960 - tallH) / 2 }}>
          <Phone scene={scene} height={tallH} />
        </div>
        {scene.callout && (
          <div style={{ position: "absolute", top: 1400, padding: "0 30px" }}>
            <Callout text={scene.callout} vertical />
          </div>
        )}
        <div style={{ position: "absolute", top: 1560, padding: "0 60px" }}>
          <Captions words={words} vertical />
        </div>
      </AbsoluteFill>
    );
  }
  const phoneLeft = layout === "phone-left";
  const textLeft = phoneLeft ? 1920 - 140 - 860 : 140;
  const phoneSide = phoneLeft ? { left: 210 } : { right: 210 };
  return (
    <AbsoluteFill>
      <div style={{ position: "absolute", left: textLeft, top: 150, width: 860 }}>
        <Heading scene={scene} vertical={false} isNewChapter={isNewChapter} />
      </div>
      {scene.callout && (
        <div style={{ position: "absolute", left: textLeft, top: 470 }}>
          <Callout text={scene.callout} vertical={false} />
        </div>
      )}
      <div style={{ position: "absolute", left: textLeft, top: 720 }}>
        <Captions words={words} vertical={false} />
      </div>
      <div style={{ position: "absolute", ...phoneSide, top: 50 + (940 - wideH) / 2 }}>
        <Phone scene={scene} height={wideH} />
      </div>
    </AbsoluteFill>
  );
};

export const Tutorial: React.FC<TutorialProps> = ({ vertical, timeline, theme = DEFAULT_THEME }) => {
  const frame = useCurrentFrame();
  const vol = theme.music ? theme.musicVolume : 0;
  const bgmVol = interpolate(frame, [0, 30, timeline.total - 60, timeline.total], [0, vol, vol, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  return (
    <ThemeCtx.Provider value={theme}>
      <TimelineCtx.Provider value={timeline}>
        <AbsoluteFill style={{ background: theme.colors.bg1 }}>
          <Background />
          {theme.music && <Audio src={staticFile("bgm-tech-house.mp3")} volume={bgmVol} loop />}
          {timeline.scenes.map((scene, i) => {
            const isNewChapter = i === 0 || timeline.scenes[i - 1].chapter !== scene.chapter;
            return (
              <Sequence key={scene.id} from={scene.from} durationInFrames={scene.frames}>
                <SceneView scene={scene} vertical={vertical} isNewChapter={isNewChapter} />
                <Audio src={staticFile(scene.audio)} />
                {i > 0 && <Audio src={staticFile("swoosh-quick.mp3")} volume={0.25} />}
                {scene.callout && (
                  <Sequence from={6}>
                    <Audio src={staticFile("pop.mp3")} volume={0.35} />
                  </Sequence>
                )}
              </Sequence>
            );
          })}
          <ProgressBar />
        </AbsoluteFill>
      </TimelineCtx.Provider>
    </ThemeCtx.Provider>
  );
};
