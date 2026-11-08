import React from "react";
import { CalculateMetadataFunction, Composition } from "remotion";
import { DEFAULT_THEME, Tutorial, TutorialProps } from "./Tutorial";
import sample from "./timeline.json";
import { Thumbnail } from "./Thumbnail";

// The pipeline passes each job's timeline via --props; Studio preview uses the sample.
const defaultTimeline = sample as unknown as TutorialProps["timeline"];

const fromTimeline: CalculateMetadataFunction<TutorialProps> = ({ props }) => ({
  durationInFrames: props.timeline.total,
  fps: props.timeline.fps,
});

export const Root: React.FC = () => (
  <>
    <Composition
      id="TutorialWide"
      component={Tutorial}
      calculateMetadata={fromTimeline}
      durationInFrames={defaultTimeline.total}
      fps={defaultTimeline.fps}
      width={1920}
      height={1080}
      defaultProps={{ vertical: false, timeline: defaultTimeline, theme: DEFAULT_THEME }}
    />
    <Composition
      id="TutorialVertical"
      component={Tutorial}
      calculateMetadata={fromTimeline}
      durationInFrames={defaultTimeline.total}
      fps={defaultTimeline.fps}
      width={1080}
      height={1920}
      defaultProps={{ vertical: true, timeline: defaultTimeline, theme: DEFAULT_THEME }}
    />
    <Composition
      id="Thumbnail"
      component={Thumbnail}
      durationInFrames={1}
      fps={30}
      width={1280}
      height={720}
      defaultProps={{
        theme: DEFAULT_THEME,
        text: "Ver todas tus contraseñas",
        badge: "PASO A PASO",
        phoneImage: "phone_thumb.jpg",
        phone: { w: 460, h: 1044 },
      }}
    />
  </>
);
