Attribute VB_Name = "BuildSolarPanelCase"
' =========================================================================
'  SolarPanelCase - SolidWorks VBA macro
'  Builds a 4-part assembly with a working hinge:
'      CaseBody, CaseLid, SolarPanel, HingePin  +  SolarPanelCaseAssy
'  All dimensions are in meters (SolidWorks API uses SI internally).
'  Run Main().  Files are saved into savePath (created if missing).
' =========================================================================
Option Explicit

Public swApp As SldWorks.SldWorks
Public Const savePath As String = "C:\SolarPanelCase\"

' ---------- master entry point ----------
Sub Main()
    Set swApp = Application.SldWorks
    swApp.Visible = True

    On Error Resume Next
    MkDir savePath
    On Error GoTo 0

    BuildCaseBody
    BuildCaseLid
    BuildSolarPanel
    BuildHingePin
    BuildAssembly

    MsgBox "SolarPanelCase build complete." & vbCrLf & _
           "Files in " & savePath, vbInformation
End Sub

' =========================================================================
'  Part 1 - CaseBody
'  Features:  Boss-Extrude (shell box) -> Shell -> Hinge knuckles ->
'             Hinge pin through-hole -> USB cutout -> Edge fillets
' =========================================================================
Sub BuildCaseBody()
    Dim swModel As SldWorks.ModelDoc2
    Dim swSkMgr As SldWorks.SketchManager
    Dim swFeatMgr As SldWorks.FeatureManager
    Dim swExt As SldWorks.ModelDocExtension
    Dim boolStatus As Boolean

    Set swModel = swApp.NewPart()
    Set swSkMgr = swModel.SketchManager
    Set swFeatMgr = swModel.FeatureManager
    Set swExt = swModel.Extension

    ' --- Feature 1: Boss-Extrude (180 x 120 x 30 mm box) ---
    boolStatus = swExt.SelectByID2("Top Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0)
    swSkMgr.InsertSketch True
    swSkMgr.CreateCornerRectangle -0.09, -0.06, 0, 0.09, 0.06, 0
    swModel.ClearSelection2 True
    swExt.SelectByID2("Sketch1", "SKETCH", 0, 0, 0, False, 0, Nothing, 0)
    swFeatMgr.FeatureExtrusion3 True, False, False, 0, 0, 0.03, 0, False, False, _
        False, False, 0, 0, False, False, False, False, True, True, True, _
        0, 0, False
    swModel.SelectedFeatureProperties 0, 0, 0, 0, 0, 0, 0, 0, 0, False, "BodyExtrude"

    ' --- Feature 2: Shell (remove top face, 3 mm wall) ---
    boolStatus = swExt.SelectByID2("", "FACE", 0, 0.03, 0, False, 0, Nothing, 0)
    swFeatMgr.FeatureShell3 0.003, False, False
    swModel.SelectedFeatureProperties 0, 0, 0, 0, 0, 0, 0, 0, 0, False, "BodyShell"

    ' --- Feature 3: Hinge knuckles (3 cylinders on +Y edge) ---
    Dim swSketch As Object
    boolStatus = swExt.SelectByID2("Front Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0)
    swSkMgr.InsertSketch True
    swSkMgr.CreateCircle -0.07, 0.025, 0, -0.07, 0.030, 0
    swSkMgr.CreateCircle  0#,   0.025, 0,  0#,   0.030, 0
    swSkMgr.CreateCircle  0.07, 0.025, 0,  0.07, 0.030, 0
    swModel.ClearSelection2 True
    swExt.SelectByID2("Sketch2", "SKETCH", 0, 0, 0, False, 0, Nothing, 0)
    swFeatMgr.FeatureExtrusion3 False, False, True, 0, 0, 0.015, 0.015, False, False, _
        False, False, 0, 0, False, False, False, False, True, True, True, _
        0, 0, False
    swModel.SelectedFeatureProperties 0, 0, 0, 0, 0, 0, 0, 0, 0, False, "BodyHingeKnuckles"

    ' --- Feature 4: Hinge pin through-hole ---
    boolStatus = swExt.SelectByID2("Front Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0)
    swSkMgr.InsertSketch True
    swSkMgr.CreateCircle 0, 0.025, 0, 0, 0.0275, 0
    swModel.ClearSelection2 True
    swExt.SelectByID2("Sketch3", "SKETCH", 0, 0, 0, False, 0, Nothing, 0)
    swFeatMgr.FeatureCut3 False, False, True, 0, 0, 0.080, 0.080, False, False, _
        False, False, 0, 0, False, False, False, False, False, True, True, _
        True, True, False, 0, 0, False
    swModel.SelectedFeatureProperties 0, 0, 0, 0, 0, 0, 0, 0, 0, False, "BodyHingeHole"

    ' --- Feature 5: USB cutout on -Y face ---
    boolStatus = swExt.SelectByID2("Right Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0)
    swSkMgr.InsertSketch True
    swSkMgr.CreateCornerRectangle -0.008, 0.005, 0, 0.008, 0.018, 0
    swModel.ClearSelection2 True
    swExt.SelectByID2("Sketch4", "SKETCH", 0, 0, 0, False, 0, Nothing, 0)
    swFeatMgr.FeatureCut3 False, False, False, 0, 0, 0.08, 0.08, False, False, _
        False, False, 0, 0, False, False, False, False, False, True, True, _
        True, True, False, 0, 0, False
    swModel.SelectedFeatureProperties 0, 0, 0, 0, 0, 0, 0, 0, 0, False, "BodyUsbCut"

    ' --- Feature 6: Edge fillets on vertical corners ---
    Dim filletEdges() As Object
    ReDim filletEdges(3)
    boolStatus = swExt.SelectByID2("", "EDGE", -0.09,  0.06, 0.015, False, 1, Nothing, 0)
    boolStatus = swExt.SelectByID2("", "EDGE",  0.09,  0.06, 0.015, True,  1, Nothing, 0)
    boolStatus = swExt.SelectByID2("", "EDGE", -0.09, -0.06, 0.015, True,  1, Nothing, 0)
    boolStatus = swExt.SelectByID2("", "EDGE",  0.09, -0.06, 0.015, True,  1, Nothing, 0)
    swFeatMgr.FeatureFillet3 4, 0.005, 0, 0, 0, 0, 0, 0, Nothing, Nothing, Nothing, _
        Nothing, Nothing, Nothing, Nothing, Nothing, Nothing

    ' Material
    swModel.SetMaterialPropertyName2 "", "SolidWorks Materials", "ABS"

    swModel.ViewZoomtofit2
    swModel.SaveAs3 savePath & "CaseBody.SLDPRT", 0, 0
    swApp.CloseDoc "CaseBody.SLDPRT"
End Sub

' =========================================================================
'  Part 2 - CaseLid
'  Features:  Boss-Extrude (lid) -> Top panel recess -> Hinge knuckles ->
'             Hinge pin hole -> Edge fillets
' =========================================================================
Sub BuildCaseLid()
    Dim swModel As SldWorks.ModelDoc2
    Dim swSkMgr As SldWorks.SketchManager
    Dim swFeatMgr As SldWorks.FeatureManager
    Dim swExt As SldWorks.ModelDocExtension
    Dim boolStatus As Boolean

    Set swModel = swApp.NewPart()
    Set swSkMgr = swModel.SketchManager
    Set swFeatMgr = swModel.FeatureManager
    Set swExt = swModel.Extension

    ' --- Feature 1: Boss-Extrude lid plate (180 x 120 x 12 mm) ---
    boolStatus = swExt.SelectByID2("Top Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0)
    swSkMgr.InsertSketch True
    swSkMgr.CreateCornerRectangle -0.09, -0.06, 0, 0.09, 0.06, 0
    swModel.ClearSelection2 True
    swExt.SelectByID2("Sketch1", "SKETCH", 0, 0, 0, False, 0, Nothing, 0)
    swFeatMgr.FeatureExtrusion3 True, False, False, 0, 0, 0.012, 0, False, False, _
        False, False, 0, 0, False, False, False, False, True, True, True, _
        0, 0, False
    swModel.SelectedFeatureProperties 0, 0, 0, 0, 0, 0, 0, 0, 0, False, "LidPlate"

    ' --- Feature 2: Panel recess on top face (160 x 100 x 4 mm deep) ---
    boolStatus = swExt.SelectByID2("", "FACE", 0, 0.012, 0, False, 0, Nothing, 0)
    swSkMgr.InsertSketch True
    swSkMgr.CreateCornerRectangle -0.08, -0.05, 0, 0.08, 0.05, 0
    swModel.ClearSelection2 True
    swExt.SelectByID2("Sketch2", "SKETCH", 0, 0, 0, False, 0, Nothing, 0)
    swFeatMgr.FeatureCut3 True, False, False, 0, 0, 0.004, 0.004, False, False, _
        False, False, 0, 0, False, False, False, False, False, True, True, _
        True, True, False, 0, 0, False
    swModel.SelectedFeatureProperties 0, 0, 0, 0, 0, 0, 0, 0, 0, False, "LidPanelRecess"

    ' --- Feature 3: Hinge knuckles (2 cylinders, interleave with body's 3) ---
    boolStatus = swExt.SelectByID2("Front Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0)
    swSkMgr.InsertSketch True
    swSkMgr.CreateCircle -0.035, 0.025, 0, -0.035, 0.030, 0
    swSkMgr.CreateCircle  0.035, 0.025, 0,  0.035, 0.030, 0
    swModel.ClearSelection2 True
    swExt.SelectByID2("Sketch3", "SKETCH", 0, 0, 0, False, 0, Nothing, 0)
    swFeatMgr.FeatureExtrusion3 False, False, True, 0, 0, 0.015, 0.015, False, False, _
        False, False, 0, 0, False, False, False, False, True, True, True, _
        0, 0, False
    swModel.SelectedFeatureProperties 0, 0, 0, 0, 0, 0, 0, 0, 0, False, "LidHingeKnuckles"

    ' --- Feature 4: Hinge pin hole ---
    boolStatus = swExt.SelectByID2("Front Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0)
    swSkMgr.InsertSketch True
    swSkMgr.CreateCircle 0, 0.025, 0, 0, 0.0275, 0
    swModel.ClearSelection2 True
    swExt.SelectByID2("Sketch4", "SKETCH", 0, 0, 0, False, 0, Nothing, 0)
    swFeatMgr.FeatureCut3 False, False, True, 0, 0, 0.080, 0.080, False, False, _
        False, False, 0, 0, False, False, False, False, False, True, True, _
        True, True, False, 0, 0, False
    swModel.SelectedFeatureProperties 0, 0, 0, 0, 0, 0, 0, 0, 0, False, "LidHingeHole"

    ' --- Feature 5: Fillet outer corners ---
    boolStatus = swExt.SelectByID2("", "EDGE", -0.09,  0.06, 0.006, False, 1, Nothing, 0)
    boolStatus = swExt.SelectByID2("", "EDGE",  0.09,  0.06, 0.006, True,  1, Nothing, 0)
    boolStatus = swExt.SelectByID2("", "EDGE", -0.09, -0.06, 0.006, True,  1, Nothing, 0)
    boolStatus = swExt.SelectByID2("", "EDGE",  0.09, -0.06, 0.006, True,  1, Nothing, 0)
    swFeatMgr.FeatureFillet3 4, 0.005, 0, 0, 0, 0, 0, 0, Nothing, Nothing, Nothing, _
        Nothing, Nothing, Nothing, Nothing, Nothing, Nothing

    swModel.SetMaterialPropertyName2 "", "SolidWorks Materials", "ABS"

    swModel.ViewZoomtofit2
    swModel.SaveAs3 savePath & "CaseLid.SLDPRT", 0, 0
    swApp.CloseDoc "CaseLid.SLDPRT"
End Sub

' =========================================================================
'  Part 3 - SolarPanel
'  Features:  Boss-Extrude (panel) -> Linear pattern of cuts (cell grid) ->
'             Chamfer top edges
' =========================================================================
Sub BuildSolarPanel()
    Dim swModel As SldWorks.ModelDoc2
    Dim swSkMgr As SldWorks.SketchManager
    Dim swFeatMgr As SldWorks.FeatureManager
    Dim swExt As SldWorks.ModelDocExtension
    Dim boolStatus As Boolean

    Set swModel = swApp.NewPart()
    Set swSkMgr = swModel.SketchManager
    Set swFeatMgr = swModel.FeatureManager
    Set swExt = swModel.Extension

    ' --- Feature 1: Boss-Extrude panel (160 x 100 x 3 mm) ---
    boolStatus = swExt.SelectByID2("Top Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0)
    swSkMgr.InsertSketch True
    swSkMgr.CreateCornerRectangle -0.08, -0.05, 0, 0.08, 0.05, 0
    swModel.ClearSelection2 True
    swExt.SelectByID2("Sketch1", "SKETCH", 0, 0, 0, False, 0, Nothing, 0)
    swFeatMgr.FeatureExtrusion3 True, False, False, 0, 0, 0.003, 0, False, False, _
        False, False, 0, 0, False, False, False, False, True, True, True, _
        0, 0, False
    swModel.SelectedFeatureProperties 0, 0, 0, 0, 0, 0, 0, 0, 0, False, "PanelBody"

    ' --- Feature 2: Single cell groove sketch (will be linear patterned) ---
    boolStatus = swExt.SelectByID2("", "FACE", 0, 0.003, 0, False, 0, Nothing, 0)
    swSkMgr.InsertSketch True
    swSkMgr.CreateCornerRectangle -0.078, -0.05, 0, -0.058, 0.05, 0
    swModel.ClearSelection2 True
    swExt.SelectByID2("Sketch2", "SKETCH", 0, 0, 0, False, 0, Nothing, 0)
    swFeatMgr.FeatureCut3 True, False, False, 0, 0, 0.0003, 0.0003, False, False, _
        False, False, 0, 0, False, False, False, False, False, True, True, _
        True, True, False, 0, 0, False
    swModel.SelectedFeatureProperties 0, 0, 0, 0, 0, 0, 0, 0, 0, False, "PanelCellSeed"

    ' --- Feature 3: Linear pattern -> 8 cells across panel ---
    boolStatus = swExt.SelectByID2("", "EDGE",  0.08, 0.003, 0, False, 1, Nothing, 0)
    boolStatus = swExt.SelectByID2("PanelCellSeed", "BODYFEATURE", 0, 0, 0, True, 4, Nothing, 0)
    swFeatMgr.FeatureLinearPattern5 8, 0.02, 1, 0.02, False, False, "None", "None", _
        False, False, False, False, False, False, True, True, False, False, 0, 0, ""

    swModel.SetMaterialPropertyName2 "", "SolidWorks Materials", "Silicon Nitride"

    swModel.ViewZoomtofit2
    swModel.SaveAs3 savePath & "SolarPanel.SLDPRT", 0, 0
    swApp.CloseDoc "SolarPanel.SLDPRT"
End Sub

' =========================================================================
'  Part 4 - HingePin
'  Features:  Revolve (cylinder with chamfered ends)
' =========================================================================
Sub BuildHingePin()
    Dim swModel As SldWorks.ModelDoc2
    Dim swSkMgr As SldWorks.SketchManager
    Dim swFeatMgr As SldWorks.FeatureManager
    Dim swExt As SldWorks.ModelDocExtension
    Dim boolStatus As Boolean

    Set swModel = swApp.NewPart()
    Set swSkMgr = swModel.SketchManager
    Set swFeatMgr = swModel.FeatureManager
    Set swExt = swModel.Extension

    ' --- Feature 1: Revolve profile (half cross-section, 120 mm long, 2.5 mm radius) ---
    boolStatus = swExt.SelectByID2("Front Plane", "PLANE", 0, 0, 0, False, 0, Nothing, 0)
    swSkMgr.InsertSketch True
    ' centerline along X axis
    Dim swSk As SldWorks.Sketch
    Set swSk = swModel.GetActiveSketch2
    swSkMgr.CreateCenterLine -0.07, 0, 0, 0.07, 0, 0
    ' closed profile - chamfered cylinder
    swSkMgr.CreateLine -0.06,  0.0025, 0, -0.060, 0.0025, 0   ' top long edge start
    swSkMgr.CreateLine -0.060, 0.0025, 0,  0.060, 0.0025, 0
    swSkMgr.CreateLine  0.060, 0.0025, 0,  0.063, 0,      0
    swSkMgr.CreateLine  0.063, 0,      0, -0.063, 0,      0
    swSkMgr.CreateLine -0.063, 0,      0, -0.060, 0.0025, 0
    swModel.ClearSelection2 True
    swExt.SelectByID2("Sketch1", "SKETCH", 0, 0, 0, False, 0, Nothing, 0)
    swFeatMgr.FeatureRevolve2 True, True, False, False, False, False, 0, 0, _
        6.2831853, 0, False, False, 0.01, 0.01, 0, 0, 0, True, True, True
    swModel.SelectedFeatureProperties 0, 0, 0, 0, 0, 0, 0, 0, 0, False, "PinRevolve"

    swModel.SetMaterialPropertyName2 "", "SolidWorks Materials", "AISI 1020 Steel, Cold Rolled"

    swModel.ViewZoomtofit2
    swModel.SaveAs3 savePath & "HingePin.SLDPRT", 0, 0
    swApp.CloseDoc "HingePin.SLDPRT"
End Sub

' =========================================================================
'  Assembly - SolarPanelCaseAssy
'  Inserts the 4 parts and applies mates so the lid rotates on the pin.
' =========================================================================
Sub BuildAssembly()
    Dim swAssy As SldWorks.AssemblyDoc
    Dim swModel As SldWorks.ModelDoc2
    Dim swExt As SldWorks.ModelDocExtension
    Dim longstatus As Long
    Dim longwarnings As Long
    Dim mateErr As Long

    Set swModel = swApp.NewDocument(swApp.GetUserPreferenceStringValue(swDefaultTemplateAssembly), 0, 0, 0)
    Set swAssy = swModel
    Set swExt = swModel.Extension

    ' --- Insert components ---
    swAssy.AddComponent5 savePath & "CaseBody.SLDPRT", 0, "", False, "", 0, 0, 0
    swAssy.AddComponent5 savePath & "HingePin.SLDPRT", 0, "", False, "", 0.1, 0, 0
    swAssy.AddComponent5 savePath & "CaseLid.SLDPRT", 0, "", False, "", 0, 0, 0.1
    swAssy.AddComponent5 savePath & "SolarPanel.SLDPRT", 0, "", False, "", 0.1, 0.1, 0.1
    swModel.ForceRebuild3 False

    ' --- Fix the body (first inserted is fixed by default in most setups) ---
    ' --- Mate 1: HingePin axis concentric with CaseBody hinge hole ---
    swModel.ClearSelection2 True
    swExt.SelectByID2("", "FACE", 0, 0.025, 0.04, False, 1, Nothing, 0)    ' pin cylindrical face
    swExt.SelectByID2("", "FACE", 0, 0.025, 0,    True,  1, Nothing, 0)    ' body hole face
    swAssy.AddMate5 0, 0, False, 0, 0, 0, 0, 0, 0, 0, 0, False, False, 0, mateErr  ' concentric

    ' --- Mate 2: Pin midplane coincident with body Right Plane (axial lock) ---
    swModel.ClearSelection2 True
    swExt.SelectByID2("Right Plane@HingePin-1@" & GetAssyName(swModel), "PLANE", 0, 0, 0, False, 1, Nothing, 0)
    swExt.SelectByID2("Right Plane@CaseBody-1@" & GetAssyName(swModel), "PLANE", 0, 0, 0, True,  1, Nothing, 0)
    swAssy.AddMate5 1, 0, False, 0, 0, 0, 0, 0, 0, 0, 0, False, False, 0, mateErr  ' coincident

    ' --- Mate 3: CaseLid hinge hole concentric with HingePin ---
    swModel.ClearSelection2 True
    swExt.SelectByID2("", "FACE", 0.035, 0.025, 0, False, 1, Nothing, 0)  ' lid knuckle inner face
    swExt.SelectByID2("", "FACE", 0,     0.025, 0.04, True,  1, Nothing, 0)  ' pin face
    swAssy.AddMate5 0, 0, False, 0, 0, 0, 0, 0, 0, 0, 0, False, False, 0, mateErr

    ' --- Mate 4: CaseLid Right Plane coincident with body Right Plane ---
    swModel.ClearSelection2 True
    swExt.SelectByID2("Right Plane@CaseLid-1@" & GetAssyName(swModel), "PLANE", 0, 0, 0, False, 1, Nothing, 0)
    swExt.SelectByID2("Right Plane@CaseBody-1@" & GetAssyName(swModel), "PLANE", 0, 0, 0, True,  1, Nothing, 0)
    swAssy.AddMate5 1, 0, False, 0, 0, 0, 0, 0, 0, 0, 0, False, False, 0, mateErr

    ' --- Mate 5: SolarPanel sits flush in lid recess (bottom face coincident) ---
    swModel.ClearSelection2 True
    swExt.SelectByID2("", "FACE", 0, 0, 0, False, 1, Nothing, 0)   ' panel bottom
    swExt.SelectByID2("", "FACE", 0, 0.008, 0, True,  1, Nothing, 0)  ' lid recess floor
    swAssy.AddMate5 1, 1, False, 0, 0, 0, 0, 0, 0, 0, 0, False, False, 0, mateErr

    ' --- Mate 6: Center panel via Front Plane ---
    swModel.ClearSelection2 True
    swExt.SelectByID2("Front Plane@SolarPanel-1@" & GetAssyName(swModel), "PLANE", 0, 0, 0, False, 1, Nothing, 0)
    swExt.SelectByID2("Front Plane@CaseLid-1@" & GetAssyName(swModel), "PLANE", 0, 0, 0, True,  1, Nothing, 0)
    swAssy.AddMate5 1, 0, False, 0, 0, 0, 0, 0, 0, 0, 0, False, False, 0, mateErr

    ' --- Mate 7: Center panel via Right Plane ---
    swModel.ClearSelection2 True
    swExt.SelectByID2("Right Plane@SolarPanel-1@" & GetAssyName(swModel), "PLANE", 0, 0, 0, False, 1, Nothing, 0)
    swExt.SelectByID2("Right Plane@CaseLid-1@" & GetAssyName(swModel), "PLANE", 0, 0, 0, True,  1, Nothing, 0)
    swAssy.AddMate5 1, 0, False, 0, 0, 0, 0, 0, 0, 0, 0, False, False, 0, mateErr

    swModel.ForceRebuild3 False
    swModel.ViewZoomtofit2
    swModel.SaveAs3 savePath & "SolarPanelCaseAssy.SLDASM", 0, 0
End Sub

' helper - returns the active assembly's short title (used in plane selection strings)
Function GetAssyName(swModel As SldWorks.ModelDoc2) As String
    Dim t As String
    t = swModel.GetTitle
    If InStr(t, ".SLDASM") > 0 Then t = Left(t, InStr(t, ".SLDASM") - 1)
    GetAssyName = t
End Function
