# User Prompt: Audiovisual Creative Tool for macOS

I need a final "CODING ASSISTANT PROMPT" for implementing a macOS desktop application
targeting Apple Silicon (M1, arm64).

## Application overview

**Brief description (2–5 sentences):**
A multimedia creative tool for audiovisual performance and production, combining
Xbox 360 Kinect motion capture with audio processing and real-time video generation.
Inspired by TouchDesigner and Ableton Live, it enables creative professionals to
create motion-reactive visuals and audio experiences. Supports both live performance
and studio production workflows.

**Target users:** Creative professionals (VJs, musicians, visual artists, multimedia performers)

**Primary use cases:**
- Capture body motion via Xbox 360 Kinect sensor
- Generate and manipulate real-time video/visuals
- Process and play audio with built-in engine
- Map motion data to visual and audio parameters
- Create audio-reactive visuals
- Perform live audiovisual sets
- Produce and edit multimedia content in studio

## Functional requirements

**Must-have features:**
- Xbox 360 Kinect input (motion capture, skeleton tracking)
- Real-time video output and visual generation
- Audio engine (playback, processing, synthesis)

**Nice-to-have features:**
- Plugin system (VST/AU synth plugins)
- MIDI controller support (input/output)
- Recording and export (save performances to file)

## UI / UX

- **Application type:** Windowed app
- **Reference apps:** TouchDesigner, Ableton Live

## Data & integrations

- **Local data storage preference:** Undecided (let coding assistant recommend)
- **External APIs or services:** None (fully offline)
- **Authentication:** Not applicable

## Technical constraints

- **Preferred technology stack:** Swift + SwiftUI
- **Cross-platform required:** No (macOS only)
- **Offline support required:** Yes

## Distribution & system requirements

- **Auto-update mechanism:** Undecided
- **Code signing & notarization:** Undecided (recommend approach)
- **Sandboxing & Mac App Store:** Outside MAS (direct download)
- **Minimum macOS version:** macOS 14 Sonoma

## Instructions

What you must do:
1) Ask me clarifying questions first.
2) Research implementation approaches, pitfalls, and best practices
   using StackOverflow, Reddit, forums, and official documentation.
3) Produce a final "CODING ASSISTANT PROMPT" that I can directly paste
   into my coding assistant to build the application.

The final prompt must be:
- explicit,
- step-by-step,
- focused on MVP delivery,
- and include acceptance criteria and a readiness checklist.
