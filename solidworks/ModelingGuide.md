# SolarPanelCase – Manual Modeling Guide

Use this if the macro fails on your SolidWorks version, or to build the parts
by hand for the demo video (showing real sketches earns more points than
running a macro that hides the work).

**All units: millimeters.** Set in `Tools → Options → Document Properties → Units → MMGS`.

---

## Part 1 — `CaseBody`

Material: **ABS**

1. **Sketch on Top Plane** → Center Rectangle from origin, **180 × 120**. Exit sketch.
2. **Boss-Extrude** → Blind, **30 mm** up. (Feature: `BodyExtrude`)
3. **Shell** → Select the top face. Thickness **3 mm**. (Feature: `BodyShell`)
4. **Sketch on Front Plane** → 3 circles, **Ø 5 mm** each, at X = –70, 0, +70, all at Y = +25. Exit.
5. **Boss-Extrude** → Mid-Plane, **15 mm**. (Feature: `BodyHingeKnuckles`)
6. **Sketch on Front Plane** → 1 circle, **Ø 2.5 mm**, at (0, 25). Exit.
7. **Extruded Cut** → Through-All, both directions. (Feature: `BodyHingeHole`)
8. **Sketch on Right Plane** → Rectangle **16 × 13** centered around Y = +11. Exit.
9. **Extruded Cut** → Through-All. (Feature: `BodyUsbCut`)
10. **Fillet** → Pick the 4 vertical outer edges. Radius **5 mm**.

Save as `CaseBody.SLDPRT`.

---

## Part 2 — `CaseLid`

Material: **ABS**

1. **Sketch on Top Plane** → Center Rectangle from origin, **180 × 120**. Exit.
2. **Boss-Extrude** → Blind, **12 mm** up. (Feature: `LidPlate`)
3. **Sketch on the top face** → Center Rectangle, **160 × 100**. Exit.
4. **Extruded Cut** → Blind, **4 mm** down. (Feature: `LidPanelRecess`)
5. **Sketch on Front Plane** → 2 circles, **Ø 5 mm**, at X = –35 and +35, Y = +25. Exit.
6. **Boss-Extrude** → Mid-Plane, **15 mm**. (Feature: `LidHingeKnuckles`)
7. **Sketch on Front Plane** → 1 circle, **Ø 2.5 mm** at (0, 25). Exit.
8. **Extruded Cut** → Through-All, both directions.
9. **Fillet** → 4 vertical outer edges, **5 mm**.

Save as `CaseLid.SLDPRT`.

---

## Part 3 — `SolarPanel`

Material: **Silicon Nitride** (or any "glass" appearance)

1. **Sketch on Top Plane** → Center Rectangle, **160 × 100**. Exit.
2. **Boss-Extrude** → Blind, **3 mm**. (Feature: `PanelBody`)
3. **Sketch on top face** → Thin rectangle **2 × 100** at the left edge of the panel. Exit.
4. **Extruded Cut** → Blind, **0.3 mm** deep. (Feature: `PanelCellSeed`)
5. **Linear Pattern** → Direction: long edge of panel (X). Spacing **20 mm**, **8 instances**.

Save as `SolarPanel.SLDPRT`.

---

## Part 4 — `HingePin`

Material: **AISI 1020 Steel, Cold Rolled**

1. **Sketch on Front Plane** → Centerline along X axis. Draw a closed profile:
   horizontal line from (–60, 2.5) to (60, 2.5), down-chamfer to (63, 0),
   back along X axis to (–63, 0), up-chamfer to (–60, 2.5). Dimension fully.
2. **Revolve** about the centerline, 360°.

Save as `HingePin.SLDPRT`.

---

## Assembly — `SolarPanelCaseAssy`

`File → New → Assembly`. Insert in this order:

1. `CaseBody` — drop at origin (it auto-fixes).
2. `HingePin`
3. `CaseLid`
4. `SolarPanel`

Apply these mates (`Insert → Mate`):

| #  | Type        | Selection 1                          | Selection 2                            |
|----|-------------|--------------------------------------|----------------------------------------|
| 1  | Concentric  | `HingePin` cylindrical face          | `CaseBody` hinge-hole inner face       |
| 2  | Coincident  | `HingePin` Right Plane               | `CaseBody` Right Plane                 |
| 3  | Concentric  | `CaseLid` hinge-hole inner face      | `HingePin` cylindrical face            |
| 4  | Coincident  | `CaseLid` Right Plane                | `CaseBody` Right Plane                 |
| 5  | Coincident  | `SolarPanel` bottom face             | `CaseLid` recess floor                 |
| 6  | Coincident  | `SolarPanel` Front Plane             | `CaseLid` Front Plane                  |
| 7  | Coincident  | `SolarPanel` Right Plane             | `CaseLid` Right Plane                  |

After mate 4 the lid should rotate freely on the hinge — drag it to confirm.

Save as `SolarPanelCaseAssy.SLDASM`.

---

## Drawings

**Part sheet (use `CaseBody`):**
`File → Make Drawing from Part` → B-size sheet → drag Front, Top, Right, and
Isometric views. Add `Smart Dimension` for the box overall, wall thickness,
hinge knuckle spacing, USB cutout. Fill in the title block. `File → Save As → PDF`.

**Assembly sheet:**
In the assembly, `Insert → Exploded View` — pull the lid up, the pin out
sideways, the panel up. Save the explode. New drawing → drag the exploded
isometric view in. `Insert → Tables → Bill of Materials`. Use `Auto Balloon`
on the view. Fill in title block. Save as PDF.
