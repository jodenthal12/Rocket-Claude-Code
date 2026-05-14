# SolarPanelCase – SolidWorks Build

Final-project SolidWorks assembly: a rugged solar panel case with a hinged lid.

## What you get

| Part            | Features                                                              |
| --------------- | --------------------------------------------------------------------- |
| `CaseBody`      | Boss-Extrude box, Shell, Hinge knuckles, Pin hole, USB cutout, Fillets |
| `CaseLid`       | Boss-Extrude plate, Panel recess (cut), Hinge knuckles, Pin hole, Fillets |
| `SolarPanel`    | Boss-Extrude plate, Cell groove cut, Linear pattern (8 cells)          |
| `HingePin`      | Revolve (chamfered cylinder)                                          |
| `SolarPanelCaseAssy` | 7 mates including a working hinge (lid rotates on pin)          |

Meets the rubric:
- 4 distinct parts (3+ required) — names have **no spaces**
- 1 intentional moving part: **the lid rotates on the hinge pin**
- Saved as `.SLDPRT` + `.SLDASM`

## How to run the macro

1. Open SolidWorks (any 2019+ version should work).
2. `Tools → Macro → New…` → save as `BuildSolarPanelCase.swp` anywhere.
3. In the VBA editor that opens, delete the empty `Sub main()` it created.
4. `File → Import File…` → pick `solidworks/BuildSolarPanelCase.bas` from this repo.
   *(Or just open the .bas in a text editor and paste the contents into a module.)*
5. Make sure the **SldWorks 20XX Type Library** reference is enabled:
   `Tools → References…` → check `SldWorks 20XX Type Library` and `SolidWorks 20XX Constant type library`.
6. Press **F5** (or `Run → Run Sub`). When prompted, run `Main`.
7. Files save to `C:\SolarPanelCase\` (folder is created if missing). To change
   the path, edit the `savePath` constant at the top of the .bas file.

## After it runs

Open `SolarPanelCaseAssy.SLDASM` and try:
- Drag the lid — it should rotate around the hinge pin (one rotational DOF).
- Expand each part's FeatureManager tree to confirm the named features.

## If a feature fails

The SolidWorks API is picky about face/edge selection by XYZ. If a feature
fails on your version, the macro stops and you can:

1. Comment out the failing sub call in `Main()` and re-run the others.
2. Open `ModelingGuide.md` and finish that part by hand — dimensions and
   feature order are listed there exactly as the macro would have built them.

## Deliverables checklist (rubric items 1–4)

- [x] **3D Model (10 pts)** — run the macro, files in `C:\SolarPanelCase\`
- [ ] **Part Sheet (5 pts)** — open `CaseBody.SLDPRT` (most complex part),
      `File → Make Drawing from Part`, pick a B-size template, drop Front/Top/Right/Iso
      views, add dimensions, set Title block, export PDF.
- [ ] **Assembly Sheet (5 pts)** — open the .SLDASM, `Insert → Exploded View`,
      make a drawing of it, add BOM (`Insert → Tables → Bill of Materials`),
      balloon the components, export PDF.
- [ ] **Demo Video (5 pts)** — 60–180 s screen recording: drag the hinge,
      open Sketch2 on `CaseBody` and Sketch1 on `HingePin` (two hardest sketches)
      so dimensions show, expand the Mates folder, narrate.

The Adobe Illustrator packaging part (item 5) is outside scope of this repo.
