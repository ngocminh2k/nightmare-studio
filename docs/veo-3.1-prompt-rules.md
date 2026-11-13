# Veo 3.1 / Omni Flash Video Prompt Rules (FlowKit Multi-Shot Standard)

Use this instruction set for every scene-to-video prompt for Google Flow and Omni Flash.

1. **Temporal Multi-Shot Structure**:
   Structure the prompt using time intervals to direct in-camera transitions and dynamic camera work:
   - **4s clips**: `0-2s: [Shot 1 starting from input image] ... 2-4s: [Climax/action response]`
   - **6s clips**: `0-3s: [Shot 1 starting from input image] ... 3-6s: [Camera transition or escalating action]`
   - **8s clips (Standard)**: `0-3s: [Shot 1 from input image] ... 3-6s: [In-camera transition / cut / angle change] ... 6-8s: [Resolution or suspense hold]`
   - **10s clips**: `0-4s: [Shot 1 establishing from input image] ... [Cut to] 4-7s: [Shot 2 angle shift / close-up] ... 7-10s: [Climax / suspense peak]`

2. **In-Camera Cinematic Transitions (Directing inside Prompt)**:
   Choose the transition that serves the story beat:
   - **Angle Switch / Cut to**: `[0-4s] Medium shot: ... [Cut to] [4-8s] Extreme close-up: ...`
   - **Whip Pan**: Camera violently whip pans, blurring the frame and snapping to reveal the new angle or threat.
   - **Focus Pull / Defocus**: Lens slowly racks focus into soft atmospheric bokeh, then sharply snaps focus onto the subject's terrified expression.
   - **Object / Shadow Wipe**: A dark shadowy figure or heavy door swings past the lens, momentarily obscuring the frame to reveal the second action.
   - **Continuous Take**: Locked-off with creeping push-in or lateral tracking when dread builds slowly without cutting.

3. **Preserve the uploaded scene image as Shot 1 Anchor**:
   The opening segment (`0-3s` / `0-4s`) MUST strictly anchor on the uploaded scene image: same character identity, wardrobe, environment, composition, and key props. The subsequent segment evolves the action or shifts angle within the same continuous scene.

4. **Visual Style, Lighting & Atmosphere**:
   Always enforce: 2.5D indie-horror dark-comic look, high-contrast chiaroscuro, volumetric darkness, deep obsidian shadows, and desaturated tones.

5. **Audio & Sound Design**:
   Include acoustic cues: sub-bass drone (40-60Hz), howling wind, creaking floorboards, faint dripping, or sudden discordant strings for jumpscares. If speech is needed, specify exact dialogue in quotes; otherwise explicitly state "no speech, ambient horror drone only."

6. **Strict Constraints**:
   Prohibit: text overlays, burned-in subtitles, watermark logos, cartoonish morphing, random anatomical glitches.

7. **Format**:
   One concise production-ready prompt in English, 320–550 characters. No markdown fences, no explanatory prelude.
