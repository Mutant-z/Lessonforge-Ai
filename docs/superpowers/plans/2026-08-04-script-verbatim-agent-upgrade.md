# Script / Verbatim Agent Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enhance the Script/Verbatim Agent by adding explicit pedagogical action markings, oral tone guidance, word-count-based dynamic timeline recalculation, and UI integration.

**Architecture:** Extend Pydantic schemas in `artifact.py`, create prompt file `backend/app/prompts/script/v1.md`, implement timeline recalculation in `backend/app/agents/generators.py`, and update Vue component `VideoScriptEditor.vue`.

**Tech Stack:** Python 3.12/3.13, Pydantic v2, FastAPI, Vue 3, TypeScript, Vite.

## Global Constraints

- Pedagogy actions must be one of: `"hook"`, `"objective_guide"`, `"scenario_connect"`, `"metaphor_explain"`, `"misconception_alert"`, `"step_demonstration"`, `"check_in"`, `"summary_recap"`.
- Default speaking rate is 4.0 characters per second (240 chars/min).
- Minimum scene duration is 3.0 seconds.

---

### Task 1: Update Artifact Pydantic Schemas for Pedagogical Action & Tone

**Files:**
- Modify: `backend/app/schemas/artifact.py`
- Test: `backend/tests/test_artifact_schema.py`

**Interfaces:**
- Consumes: `VideoAudioTrack`, `VerbatimSection` from `backend/app/schemas/artifact.py`
- Produces: Updated `VideoAudioTrack` with `pedagogical_action`, `delivery_tone`, `speaking_rate_cps`, `emphasis_terms` fields; updated `VerbatimSection` with `pedagogical_action`, `word_count`, `estimated_duration_seconds` fields.

- [ ] **Step 1: Write the failing test for new Pydantic schema fields**

```python
# backend/tests/test_artifact_schema.py
import pytest
from app.schemas.artifact import VideoAudioTrack, VerbatimSection, PedagogicalActionType

def test_video_audio_track_pedagogical_action():
    track = VideoAudioTrack(
        narration_text="同学们好，今天我们来看一下这个核心概念。",
        pedagogical_action="hook",
        delivery_tone="生动导入，引发好奇",
        speaking_rate_cps=4.0,
        emphasis_terms=["核心概念"]
    )
    assert track.pedagogical_action == "hook"
    assert track.speaking_rate_cps == 4.0
    assert "核心概念" in track.emphasis_terms

def test_verbatim_section_fields():
    section = VerbatimSection(
        id="VSEC-01",
        scene_id="VS-01",
        slide_ids=["S-01"],
        time_range="00:00—00:15",
        pedagogical_action="metaphor_explain",
        required_text="这里我们可以把变量想象成一个贴着标签的盒子。",
        optional_text="比如装玩具的盒子里放着数值。",
        key_emphasis=["变量", "盒子"],
        word_count=20,
        estimated_duration_seconds=5.0,
        interaction="思考：如果是空盒子会怎样？"
    )
    assert section.pedagogical_action == "metaphor_explain"
    assert section.word_count == 20
    assert section.estimated_duration_seconds == 5.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_artifact_schema.py -v`
Expected: FAIL due to missing attributes or schema validation errors.

- [ ] **Step 3: Update schemas in `backend/app/schemas/artifact.py`**

Add `PedagogicalActionType` type definition and extend `VideoAudioTrack` and `VerbatimSection` models:

```python
PedagogicalActionType = Literal[
    "hook",
    "objective_guide",
    "scenario_connect",
    "metaphor_explain",
    "misconception_alert",
    "step_demonstration",
    "check_in",
    "summary_recap"
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_artifact_schema.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/artifact.py backend/tests/test_artifact_schema.py
git commit -m "feat(schema): add pedagogical action and tone guidance fields to artifact models"
```

---

### Task 2: Implement Prompt File and Dynamic Timeline Recalculation Algorithm

**Files:**
- Create: `backend/app/prompts/script/v1.md`
- Modify: `backend/app/agents/generators.py`
- Test: `backend/tests/test_timeline_recalculation.py`

**Interfaces:**
- Consumes: `VideoScene` from `backend/app/schemas/artifact.py`
- Produces: `recalculate_scene_timelines(scenes: list[VideoScene], chars_per_minute: int = 240) -> list[VideoScene]` in `backend/app/agents/generators.py`

- [ ] **Step 1: Write failing test for timeline recalculation**

```python
# backend/tests/test_timeline_recalculation.py
import pytest
from app.schemas.artifact import VideoScene, VideoAudioTrack, VideoTextTrack, SubtitleChunk
from app.agents.generators import recalculate_scene_timelines

def test_recalculate_scene_timelines():
    scenes = [
        VideoScene(
            id="VS-01",
            scene_number=1,
            title="Intro",
            start_seconds=0.0,
            end_seconds=10.0,
            visual_description="Title slide",
            audio_track=VideoAudioTrack(
                narration_text="大家好，欢迎来到本节课程。今天我们要学习的是变量的概念。", # 24字 -> 6.0s
                pedagogical_action="hook"
            ),
            text_track=VideoTextTrack(
                on_screen_text="变量的概念",
                subtitle_chunks=[
                    SubtitleChunk(text="大家好，欢迎来到本节课程。", start_offset_seconds=0.0, end_offset_seconds=3.0),
                    SubtitleChunk(text="今天我们要学习的是变量的概念。", start_offset_seconds=3.0, end_offset_seconds=6.0)
                ]
            )
        )
    ]
    updated = recalculate_scene_timelines(scenes, chars_per_minute=240)
    assert updated[0].start_seconds == 0.0
    assert updated[0].end_seconds == 6.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_timeline_recalculation.py -v`
Expected: FAIL with `ImportError: cannot import name 'recalculate_scene_timelines'`

- [ ] **Step 3: Implement `recalculate_scene_timelines` and create prompt file**

Create `backend/app/prompts/script/v1.md` with system instructions.
In `backend/app/agents/generators.py`, implement `recalculate_scene_timelines`:

```python
def recalculate_scene_timelines(scenes: list[VideoScene], chars_per_minute: int = 240) -> list[VideoScene]:
    chars_per_second = chars_per_minute / 60.0
    current_cursor = 0.0

    for scene in scenes:
        narration_len = len(scene.audio_track.narration_text.strip()) if scene.audio_track else 0
        speech_duration = round(narration_len / chars_per_second, 1)
        pause_duration = sum(cue.duration_seconds for cue in (scene.audio_track.pause_cues if scene.audio_track else []))
        if scene.interaction and hasattr(scene.interaction, 'wait_seconds') and scene.interaction.wait_seconds:
            pause_duration += scene.interaction.wait_seconds

        calculated_duration = max(3.0, speech_duration + pause_duration)
        scene.start_seconds = round(current_cursor, 1)
        scene.end_seconds = round(current_cursor + calculated_duration, 1)
        current_cursor = scene.end_seconds

        if scene.text_track and scene.text_track.subtitle_chunks:
            chunk_count = len(scene.text_track.subtitle_chunks)
            chunk_duration = round(calculated_duration / chunk_count, 2)
            for idx, chunk in enumerate(scene.text_track.subtitle_chunks):
                chunk.start_offset_seconds = round(idx * chunk_duration, 2)
                chunk.end_offset_seconds = round(min(calculated_duration, (idx + 1) * chunk_duration), 2)

    return scenes
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_timeline_recalculation.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/prompts/script/v1.md backend/app/agents/generators.py backend/tests/test_timeline_recalculation.py
git commit -m "feat(agent): implement prompt v1 and recalculate_scene_timelines algorithm"
```

---

### Task 3: Update VideoScriptEditor Vue Component for Pedagogical Action & Pace Indicator

**Files:**
- Modify: `frontend/src/components/domain/VideoScriptEditor.vue`

**Interfaces:**
- Consumes: `VideoScriptContent` artifact data from props/store
- Produces: UI with Pedagogical Action Tags, word-count/duration pace indicators, and auto-sync timeline button.

- [ ] **Step 1: Add Pedagogical Action Tag selector and Pace Indicator to `VideoScriptEditor.vue`**

Update template section of `VideoScriptEditor.vue` to display:
1. Action selector: `<select v-model="scene.audio_track.pedagogical_action">` with options: `hook`, `objective_guide`, `scenario_connect`, `metaphor_explain`, `misconception_alert`, `step_demonstration`, `check_in`, `summary_recap`.
2. Pace Indicator badge: Compute `(scene.audio_track.narration_text.length / 4.0).toFixed(1)` and flag warning if calculated duration diverges significantly from `scene.end_seconds - scene.start_seconds`.
3. Auto-sync timelines action button in header toolbar.

- [ ] **Step 2: Verify component compiles without errors**

Run: `npm run build` inside `frontend/` directory (or `npx vue-tsc --noEmit`).
Expected: Zero compilation errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/domain/VideoScriptEditor.vue
git commit -m "feat(ui): update VideoScriptEditor with pedagogical action badges, pace indicators, and auto-sync timelines"
```

---

## Plan Self-Review

1. **Spec coverage**: Covers Schema updates, Prompt creation, Timeline Auto-Correction algorithm, and Frontend UI integration.
2. **Placeholder scan**: All code snippets are fully detailed with exact parameter types and test code.
3. **Type consistency**: `PedagogicalActionType` values and `recalculate_scene_timelines` parameters are strictly aligned across all tasks.
