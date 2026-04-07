# FreeCAD Integration Test Cases

| Test file name                              | Date added | Original FreeCAD Version | Notes                                                          |
|---------------------------------------------|------------|--------------------------|----------------------------------------------------------------|
| PD_PadWithMidplaneFC102.FCStd               | 2026-02-06 | 1.0.2                    | Pad using the deprecated midplane property                     |
| PD_Abdeckung.FCStd                          | 2026-02-15 | 1.2-dev                  | Simple cover with pad, thickness and a mirror                  |
| PD_Funnels.FCStd                            | 2026-02-15 | 1.2-dev                  | Simple funnel with pipe                                        |
| PD_Pins.FCStd                               | 2026-02-15 | 1.2-dev                  | Some pads and lofts with draft angles                          |
| PD_PipeEndCap.FCStd                         | 2026-02-15 | 1.2-dev                  | Simple model of an end cap                                     |
| PD_SpoolHolder.FCStd                        | 2026-02-15 | 1.2-dev                  | Simple extruded part with revolution                           |
| PD_TubeCover.FCStd                          | 2026-02-15 | 1.2-dev                  | Tubes, binders, booleans, and some chamfers                    |
| AssemblyExample.FCStd                       | 2026-02-15 | 1.2-dev                  | Assembly Example file                                          |
| Duct_linear_rectangular_complete.FCStd      | 2026-03-15 | 1.0                      | HVAC duct with TechDraw, Spreadsheet, Materials, Part booleans |
| Precast_Beam_for_Slabs_BIM_Parametric.FCStd | 2026-03-15 | 1.0                      | BIM parametric beam with Spreadsheet-driven dimensions         |
| Hirth-joint-generator.FCStd                 | 2026-03-15 | 0.20                     | Complex Hirth joint with Spreadsheet parameters                |
| Parametric_LiPo.FCStd                       | 2026-03-15 | 0.21                     | Parametric LiPo battery with App::Part and Spreadsheet         |
| Profile_Bosch_30x30mm.FCStd                 | 2026-03-15 | 0.17                     | Extruded aluminium profile with BSpline sketch geometry        |
| Googly_eyes.FCStd                           | 2026-03-15 | 0.21                     | Parametric googly eyes with Ellipse sketch geometry            |
| Sketcher_ArcOfEllipse.FCStd                 | 2026-03-15 | 1.1                      | ArcOfEllipse sketch geometry                                   |
| Sketcher_ArcOfParabola.FCStd                | 2026-03-15 | 1.1                      | ArcOfParabola sketch geometry                                  |
| Sketcher_ArcOfHyperbola.FCStd               | 2026-03-15 | 1.1                      | ArcOfHyperbola sketch geometry                                 |
| T8_housing_bracket.FCStd                    | 2026-03-15 | 0.20                     | PartDesign::Hole with PolarPattern                             |
| UHF_Antenna_Phasma.FCStd                    | 2026-03-21 | 1.0-dev                  | KiCAD-derived PCB antenna with 752 objects, CERN OHL v1.2      |
| FL_AP3030S8.FCStd                           | 2026-03-27 | 0.19                     | Aluminium slot profile 30x30mm with DatumLine                  |
| FL_AP3030S8_BracketSmallSingleStone.FCStd   | 2026-03-27 | 0.19                     | Profile bracket assembly with single stone                     |
| FL_AP3030S8_BracketSmallTwoStones.FCStd     | 2026-03-27 | 0.19                     | Profile bracket assembly with two stones                       |
| FL_AP3030S8_Cap.FCStd                       | 2026-03-27 | 0.19                     | Profile end cap with SubtractivePipe                           |
| FL_AP3030S8_ConnectorSquare.FCStd           | 2026-03-27 | 0.19                     | Square connector for slot profile                              |
| FL_AP3030S8_InnerBracket.FCStd              | 2026-03-27 | 0.19                     | Inner bracket with Hole feature                                |
| FL_AP3030S8_InnerBracketWithScrews.FCStd    | 2026-03-27 | 0.19                     | Inner bracket assembly with screws                             |
| FL_AP3030S8_StoneM6Heavy.FCStd              | 2026-03-27 | 0.19                     | M6 heavy T-slot stone with Hole and Groove                     |
| FL_AP3030S8_StoneM8Heavy.FCStd              | 2026-03-27 | 0.19                     | M8 heavy T-slot stone with Hole and Groove                     |
| FL_AP3030S8_TNutM6.FCStd                    | 2026-03-27 | 0.19                     | M6 T-nut with Hole and Chamfer                                 |
| FL_ISO4029_SetScrewCupPoint.FCStd           | 2026-03-27 | 0.19                     | Set screw with Groove and Revolution                           |
| MG_ULN2003DriverBoard.FCStd                 | 2026-03-27 | 0.19                     | ULN2003 driver board with AdditivePipe                         |
| MG_SampleBox.FCStd                          | 2026-03-27 | 0.19                     | Sample box with Chamfer, Fillet, Mirrored                      |
| MG_B3FKeycap.FCStd                          | 2026-03-27 | 0.19                     | Keycap with Pad and Revolution                                 |
| MG_NeoPixelBubble.FCStd                     | 2026-03-27 | 0.19                     | NeoPixel bubble with Pocket and Revolution                     |
| MG_XYZCube.FCStd                            | 2026-03-27 | 0.19                     | XYZ calibration cube with Pad and Pocket                       |
| MG_AxisCross.FCStd                          | 2026-03-27 | 0.19                     | Axis cross with Chamfer and Pad                                |
| MG_DupontCable.FCStd                        | 2026-03-27 | 0.19                     | Dupont cable connector with AdditiveLoft                       |
| MG_GigglingEye.FCStd                        | 2026-03-27 | 0.19                     | Giggling eye toy with Fillet and Revolution                    |
| MG_MotorbikeMobileSupport.FCStd             | 2026-03-27 | 0.19                     | Motorbike phone mount with Fillet                              |
| OBJ_CherryKeycap.FCStd                      | 2026-03-27 | 0.19                     | Cherry MX keycap with AdditiveLoft and Thickness               |
| OBJ_CherryMXPCB.FCStd                       | 2026-03-27 | 0.19                     | Cherry MX PCB mount with Pad, Pocket, Fillet                   |
| Draft_Kitchen_cabinet_base.FCStd            | 2026-04-05 | 1.0                      | Kitchen cabinet with Draft clone, patharray, shape2dview       |
| Duct_flex_complete.FCStd                    | 2026-04-05 | 1.0                      | Flexible HVAC duct with Draft bezcurve and wire                |
| FL_PinHeader2x18.FCStd                      | 2026-04-06 | 0.14                     | 2x18 pin header with Part Array, Loft, Cut, Compound           |
| FL_ServoSG90.FCStd                          | 2026-04-06 | 0.16                     | SG90 servo motor with Part primitives and Fusion               |
| FL_ToyDoll.FCStd                            | 2026-04-06 | 0.18                     | Articulated toy doll with multiple PartDesign Bodies           |
