import os

import qt
import vtk

import slicer
from slicer.util import settingsValue
from slicer.util import VTKObservationMixin

from . import DataProbeUtil


class SliceAnnotations(VTKObservationMixin):
    """Implement the Qt window showing settings for Slice View Annotations
    """

    DEFAULTS = {
        "enabled": 1,
        "displayLevel": 0,
        "topLeft": 0,
        "topRight": 0,
        "bottomLeft": 1,
        "fontFamily": "Times",
        "fontSize": 14,
        "bgDICOMAnnotationsPersistence": 0,
    }

    def __init__(self, layoutManager=None):
        VTKObservationMixin.__init__(self)

        self.layoutManager = layoutManager
        if self.layoutManager is None:
            self.layoutManager = slicer.app.layoutManager()
        self.layoutManager.connect("destroyed()", self.onLayoutManagerDestroyed)

        self.dataProbeUtil = DataProbeUtil.DataProbeUtil()

        self.dicomVolumeNode = 0

        # Cache recently used extracted DICOM values.
        # Getting all necessary DICOM values from the database (tag cache)
        # would slow down slice browsing significantly.
        # We may have several different volumes shown in different slice views,
        # so we keep in the cache a number of items, not just 2.
        self.extractedDICOMValuesCacheSize = 12
        import collections
        self.extractedDICOMValuesCache = collections.OrderedDict()

        self.sliceViewNames = []
        self.popupGeometry = qt.QRect()
        self.cornerTexts = []
        # Bottom Left Corner Text
        self.cornerTexts.append({
            "1-Label": {"text": "", "category": "A"},
            "2-Foreground": {"text": "", "category": "A"},
            "3-Background": {"text": "", "category": "A"}
        })
        # Bottom Right Corner Text
        # Not used - orientation figure may be drawn there
        self.cornerTexts.append({
            "1-TR": {"text": "", "category": "A"},
            "2-TE": {"text": "", "category": "A"}
        })
        # Top Left Corner Text
        self.cornerTexts.append({
            "1-PatientName": {"text": "", "category": "B"},
            "2-PatientID": {"text": "", "category": "A"},
            "3-PatientInfo": {"text": "", "category": "B"},
            "4-Bg-SeriesDate": {"text": "", "category": "B"},
            "5-Fg-SeriesDate": {"text": "", "category": "B"},
            "6-Bg-SeriesTime": {"text": "", "category": "C"},
            "7-Bg-SeriesTime": {"text": "", "category": "C"},
            "8-Bg-SeriesDescription": {"text": "", "category": "C"},
            "9-Fg-SeriesDescription": {"text": "", "category": "C"}
        })
        # Top Right Corner Text
        self.cornerTexts.append({
            "1-Institution-Name": {"text": "", "category": "B"},
            "2-Referring-Phisycian": {"text": "", "category": "B"},
            "3-Manufacturer": {"text": "", "category": "C"},
            "4-Model": {"text": "", "category": "C"},
            "5-Patient-Position": {"text": "", "category": "A"},
            "6-TR": {"text": "", "category": "A"},
            "7-TE": {"text": "", "category": "A"},
            "8-SlabReconstructionThickness": {"text": "", "category": "A"},
            "9-SlabReconstructionType": {"text": "", "category": "A"}
        })

        #
        self.scene = slicer.mrmlScene
        self.sliceViews = {}

        # If there are no user settings load defaults
        def _defaultValue(key, **kwargs):
            settingsKey = f"DataProbe/sliceViewAnnotations.{key}"
            return settingsValue(settingsKey, SliceAnnotations.DEFAULTS[key], **kwargs)

        self.sliceViewAnnotationsEnabled = _defaultValue("enabled", converter=int)

        self.annotationsDisplayAmount = _defaultValue("displayLevel", converter=int)
        self.topLeft = _defaultValue("topLeft", converter=int)
        self.topRight = _defaultValue("topRight", converter=int)
        self.bottomLeft = _defaultValue("bottomLeft", converter=int)
        self.fontFamily = _defaultValue("fontFamily")
        self.fontSize = _defaultValue("fontSize", converter=int)
        self.backgroundDICOMAnnotationsPersistence = _defaultValue("bgDICOMAnnotationsPersistence", converter=int)

        self.sliceViewAnnotationsEnabledparameter = "sliceViewAnnotationsEnabled"
        self.parameterNode = self.dataProbeUtil.getParameterNode()
        self.addObserver(self.parameterNode, vtk.vtkCommand.ModifiedEvent, self.updateGUIFromMRML)

        self.maximumTextLength = 35

        # Support forcing display of top right corner annotations if slab reconstruction is enabled
        # See https://github.com/Slicer/Slicer/issues/7092
        self.allowForcingTopRightVisibility = True

        self.create()

        if self.sliceViewAnnotationsEnabled:
            self.updateSliceViewFromGUI()

    def create(self):
        # Instantiate and connect widgets ...
        loader = qt.QUiLoader()
        path = os.path.join(os.path.dirname(__file__), "Resources", "UI", "settings.ui")
        qfile = qt.QFile(path)
        qfile.open(qt.QFile.ReadOnly)
        self.window = loader.load(qfile)
        window = self.window

        find = slicer.util.findChildren
        self.cornerTextParametersCollapsibleButton = find(window, "cornerTextParametersCollapsibleButton")[0]
        self.sliceViewAnnotationsCheckBox = find(window, "sliceViewAnnotationsCheckBox")[0]
        self.sliceViewAnnotationsCheckBox.checked = self.sliceViewAnnotationsEnabled

        self.activateCornersGroupBox = find(window, "activateCornersGroupBox")[0]
        self.topLeftCheckBox = find(window, "topLeftCheckBox")[0]
        self.topLeftCheckBox.checked = self.topLeft
        self.topRightCheckBox = find(window, "topRightCheckBox")[0]
        self.topRightCheckBox.checked = self.topRight

        self.bottomLeftCheckBox = find(window, "bottomLeftCheckBox")[0]
        self.bottomLeftCheckBox.checked = self.bottomLeft

        self.level1RadioButton = find(window, "level1RadioButton")[0]
        self.level2RadioButton = find(window, "level2RadioButton")[0]
        self.level3RadioButton = find(window, "level3RadioButton")[0]
        radioButtons = [self.level1RadioButton, self.level2RadioButton, self.level3RadioButton]
        radioButtons[self.annotationsDisplayAmount].checked = True

        self.fontPropertiesGroupBox = find(window, "fontPropertiesGroupBox")[0]
        self.timesFontRadioButton = find(window, "timesFontRadioButton")[0]
        self.arialFontRadioButton = find(window, "arialFontRadioButton")[0]
        if self.fontFamily == "Times":
            self.timesFontRadioButton.checked = True
        else:
            self.arialFontRadioButton.checked = True

        self.fontSizeSpinBox = find(window, "fontSizeSpinBox")[0]
        self.fontSizeSpinBox.value = self.fontSize

        self.backgroundPersistenceCheckBox = find(window, "backgroundPersistenceCheckBox")[0]
        self.backgroundPersistenceCheckBox.checked = self.backgroundDICOMAnnotationsPersistence

        self.annotationsAmountGroupBox = find(window, "annotationsAmountGroupBox")[0]

        self.restoreDefaultsButton = find(window, "restoreDefaultsButton")[0]

        self.updateEnabledButtons()

        # connections
        self.sliceViewAnnotationsCheckBox.connect("clicked()", self.onSliceViewAnnotationsCheckBox)

        self.topLeftCheckBox.connect("clicked()", self.onCornerTextsActivationCheckBox)
        self.topRightCheckBox.connect("clicked()", self.onCornerTextsActivationCheckBox)
        self.bottomLeftCheckBox.connect("clicked()", self.onCornerTextsActivationCheckBox)
        self.timesFontRadioButton.connect("clicked()", self.onFontFamilyRadioButton)
        self.arialFontRadioButton.connect("clicked()", self.onFontFamilyRadioButton)
        self.fontSizeSpinBox.connect("valueChanged(int)", self.onFontSizeSpinBox)

        self.level1RadioButton.connect("clicked()", self.onDisplayDisplayLevelRadioButton)
        self.level2RadioButton.connect("clicked()", self.onDisplayDisplayLevelRadioButton)
        self.level3RadioButton.connect("clicked()", self.onDisplayDisplayLevelRadioButton)

        self.backgroundPersistenceCheckBox.connect("clicked()", self.onBackgroundLayerPersistenceCheckBox)

        self.restoreDefaultsButton.connect("clicked()", self.restoreDefaultValues)

    def onLayoutManagerDestroyed(self):
        self.layoutManager = slicer.app.layoutManager()
        if self.layoutManager:
            self.layoutManager.connect("destroyed()", self.onLayoutManagerDestroyed)

    def onSliceViewAnnotationsCheckBox(self):
        self.sliceViewAnnotationsEnabled = int(self.sliceViewAnnotationsCheckBox.checked)

        settings = qt.QSettings()
        settings.setValue("DataProbe/sliceViewAnnotations.enabled", self.sliceViewAnnotationsEnabled)

        self.updateEnabledButtons()
        self.updateSliceViewFromGUI()

    def onDisplayDisplayLevelRadioButton(self):
        if self.level1RadioButton.checked:
            self.annotationsDisplayAmount = 0
        elif self.level2RadioButton.checked:
            self.annotationsDisplayAmount = 1
        elif self.level3RadioButton.checked:
            self.annotationsDisplayAmount = 2

        settings = qt.QSettings()
        settings.setValue("DataProbe/sliceViewAnnotations.displayLevel",
                          self.annotationsDisplayAmount)

        self.updateSliceViewFromGUI()

    def onBackgroundLayerPersistenceCheckBox(self):
        self.backgroundDICOMAnnotationsPersistence = int(self.backgroundPersistenceCheckBox.checked)
        settings = qt.QSettings()
        settings.setValue("DataProbe/sliceViewAnnotations.bgDICOMAnnotationsPersistence",
                          self.backgroundDICOMAnnotationsPersistence)
        self.updateSliceViewFromGUI()

    def onCornerTextsActivationCheckBox(self):
        self.topLeft = int(self.topLeftCheckBox.checked)
        self.topRight = int(self.topRightCheckBox.checked)
        self.bottomLeft = int(self.bottomLeftCheckBox.checked)

        self.updateSliceViewFromGUI()

        settings = qt.QSettings()
        settings.setValue("DataProbe/sliceViewAnnotations.topLeft",
                          self.topLeft)
        settings.setValue("DataProbe/sliceViewAnnotations.topRight",
                          self.topRight)
        settings.setValue("DataProbe/sliceViewAnnotations.bottomLeft",
                          self.bottomLeft)

    def onFontFamilyRadioButton(self):
        # Updating font size and family
        if self.timesFontRadioButton.checked:
            self.fontFamily = "Times"
        else:
            self.fontFamily = "Arial"
        settings = qt.QSettings()
        settings.setValue("DataProbe/sliceViewAnnotations.fontFamily",
                          self.fontFamily)
        self.updateSliceViewFromGUI()

    def onFontSizeSpinBox(self):
        self.fontSize = self.fontSizeSpinBox.value
        settings = qt.QSettings()
        settings.setValue("DataProbe/sliceViewAnnotations.fontSize",
                          self.fontSize)
        self.updateSliceViewFromGUI()

    def restoreDefaultValues(self):

        def _defaultValue(key):
            return SliceAnnotations.DEFAULTS[key]

        self.sliceViewAnnotationsCheckBox.checked = _defaultValue("enabled")
        self.sliceViewAnnotationsEnabled = _defaultValue("enabled")
        self.updateEnabledButtons()

        radioButtons = [self.level1RadioButton, self.level2RadioButton, self.level3RadioButton]
        radioButtons[_defaultValue("displayLevel")].checked = True
        self.annotationsDisplayAmount = _defaultValue("displayLevel")

        self.topLeftCheckBox.checked = _defaultValue("topLeft")
        self.topLeft = _defaultValue("topLeft")

        self.topRightCheckBox.checked = _defaultValue("topRight")
        self.topRight = _defaultValue("topRight")

        self.bottomLeftCheckBox.checked = _defaultValue("bottomLeft")
        self.bottomLeft = _defaultValue("bottomLeft")

        self.fontSizeSpinBox.value = _defaultValue("fontSize")
        self.timesFontRadioButton.checked = _defaultValue("fontFamily") == "Times"
        self.fontFamily = _defaultValue("fontFamily")

        self.backgroundDICOMAnnotationsPersistence = _defaultValue("bgDICOMAnnotationsPersistence")
        self.backgroundPersistenceCheckBox.checked = _defaultValue("bgDICOMAnnotationsPersistence")

        settings = qt.QSettings()
        settings.setValue("DataProbe/sliceViewAnnotations.enabled", self.sliceViewAnnotationsEnabled)
        settings.setValue("DataProbe/sliceViewAnnotations.topLeft", self.topLeft)
        settings.setValue("DataProbe/sliceViewAnnotations.topRight", self.topRight)
        settings.setValue("DataProbe/sliceViewAnnotations.bottomLeft", self.bottomLeft)
        settings.setValue("DataProbe/sliceViewAnnotations.fontFamily", self.fontFamily)
        settings.setValue("DataProbe/sliceViewAnnotations.fontSize", self.fontSize)
        settings.setValue("DataProbe/sliceViewAnnotations.bgDICOMAnnotationsPersistence",
                          self.backgroundDICOMAnnotationsPersistence)

        self.updateSliceViewFromGUI()

    def updateGUIFromMRML(self, caller, event):
        if self.parameterNode.GetParameter(self.sliceViewAnnotationsEnabledparameter) == "":
            # parameter does not exist - probably initializing
            return
        self.sliceViewAnnotationsEnabled = int(self.parameterNode.GetParameter(self.sliceViewAnnotationsEnabledparameter))
        self.updateSliceViewFromGUI()

    def updateEnabledButtons(self):
        enabled = self.sliceViewAnnotationsEnabled

        self.cornerTextParametersCollapsibleButton.enabled = enabled
        self.activateCornersGroupBox.enabled = enabled
        self.fontPropertiesGroupBox.enabled = enabled
        self.annotationsAmountGroupBox.enabled = enabled

    def updateSliceViewFromGUI(self):
        if not self.sliceViewAnnotationsEnabled:
            self.removeObservers(method=self.updateViewAnnotations)
            self.removeObservers(method=self.updateGUIFromMRML)
            return

        # Create corner annotations if have not created already
        if len(self.sliceViewNames) == 0:
            self.createCornerAnnotations()

        for sliceViewName in self.sliceViewNames:
            sliceWidget = self.layoutManager.sliceWidget(sliceViewName)
            if sliceWidget:
                sl = sliceWidget.sliceLogic()
                self.updateCornerAnnotation(sl)

    def createGlobalVariables(self):
        self.sliceViewNames = []
        self.sliceWidgets = {}
        self.sliceViews = {}
        self.renderers = {}

    def createCornerAnnotations(self):
        self.createGlobalVariables()
        self.sliceViewNames = list(self.layoutManager.sliceViewNames())
        for sliceViewName in self.sliceViewNames:
            self.addSliceViewObserver(sliceViewName)
            self.createActors(sliceViewName)

    def addSliceViewObserver(self, sliceViewName):
        sliceWidget = self.layoutManager.sliceWidget(sliceViewName)
        self.sliceWidgets[sliceViewName] = sliceWidget
        sliceView = sliceWidget.sliceView()

        renderWindow = sliceView.renderWindow()
        renderer = renderWindow.GetRenderers().GetItemAsObject(0)
        self.renderers[sliceViewName] = renderer

        self.sliceViews[sliceViewName] = sliceView
        sliceLogic = sliceWidget.sliceLogic()
        self.addObserver(sliceLogic, vtk.vtkCommand.ModifiedEvent, self.updateViewAnnotations)

    def createActors(self, sliceViewName):
        sliceWidget = self.layoutManager.sliceWidget(sliceViewName)
        self.sliceWidgets[sliceViewName] = sliceWidget

    def updateViewAnnotations(self, caller, event):
        if not self.sliceViewAnnotationsEnabled:
            # when self.sliceViewAnnotationsEnabled is set to false
            # then annotation and scalar bar gets hidden, therefore
            # we have nothing to do here
            return

        layoutManager = self.layoutManager
        if layoutManager is None:
            return
        sliceViewNames = layoutManager.sliceViewNames()
        for sliceViewName in sliceViewNames:
            if sliceViewName not in self.sliceViewNames:
                self.sliceViewNames.append(sliceViewName)
                self.addSliceViewObserver(sliceViewName)
                self.createActors(sliceViewName)
                self.updateSliceViewFromGUI()
        self.makeAnnotationText(caller)

    def updateCornerAnnotation(self, sliceLogic):

        sliceNode = sliceLogic.GetBackgroundLayer().GetSliceNode()
        sliceViewName = sliceNode.GetLayoutName()

        enabled = self.sliceViewAnnotationsEnabled

        cornerAnnotation = self.sliceViews[sliceViewName].cornerAnnotation()

        if enabled:
            # Font
            cornerAnnotation.SetMaximumFontSize(self.fontSize)
            cornerAnnotation.SetMinimumFontSize(self.fontSize)
            cornerAnnotation.SetNonlinearFontScaleFactor(1)
            textProperty = cornerAnnotation.GetTextProperty()
            if self.fontFamily == "Times":
                textProperty.SetFontFamilyToTimes()
            else:
                textProperty.SetFontFamilyToArial()
            slicer.app.applicationLogic().UseCustomFontFile(textProperty)
            # Text
            self.makeAnnotationText(sliceLogic)
        else:
            # Clear Annotations
            for position in range(4):
                cornerAnnotation.SetText(position, "")

        self.sliceViews[sliceViewName].scheduleRender()

    def makeAnnotationText(self, sliceLogic):
        self.resetTexts()
        sliceCompositeNode = sliceLogic.GetSliceCompositeNode()
        if not sliceCompositeNode:
            return

        # Get the layers
        backgroundLayer = sliceLogic.GetBackgroundLayer()
        foregroundLayer = sliceLogic.GetForegroundLayer()
        labelLayer = sliceLogic.GetLabelLayer()

        # Get the volumes
        backgroundVolume = backgroundLayer.GetVolumeNode()
        foregroundVolume = foregroundLayer.GetVolumeNode()
        labelVolume = labelLayer.GetVolumeNode()

        # Get slice view name
        sliceNode = backgroundLayer.GetSliceNode()
        if not sliceNode:
            return
        sliceViewName = sliceNode.GetLayoutName()

        if self.sliceViews[sliceViewName]:
            #
            # Update slice corner annotations
            #
            # Case I: Both background and foregraound
            if (backgroundVolume is not None and foregroundVolume is not None):
                if self.bottomLeft:
                    foregroundOpacity = sliceCompositeNode.GetForegroundOpacity()
                    backgroundVolumeName = backgroundVolume.GetName()
                    foregroundVolumeName = foregroundVolume.GetName()
                    self.cornerTexts[0]["3-Background"]["text"] = "B: " + backgroundVolumeName
                    self.cornerTexts[0]["2-Foreground"]["text"] = "F: " + foregroundVolumeName + " (" + str(
                        "%d" % (foregroundOpacity * 100)) + "%)"

                bgUids = backgroundVolume.GetAttribute("DICOM.instanceUIDs")
                fgUids = foregroundVolume.GetAttribute("DICOM.instanceUIDs")
                if (bgUids and fgUids):
                    bgUid = bgUids.partition(" ")[0]
                    fgUid = fgUids.partition(" ")[0]
                    self.dicomVolumeNode = 1
                    self.makeDicomAnnotation(bgUid, fgUid, sliceViewName)
                elif (bgUids and self.backgroundDICOMAnnotationsPersistence):
                    uid = bgUids.partition(" ")[0]
                    self.dicomVolumeNode = 1
                    self.makeDicomAnnotation(uid, None, sliceViewName)
                else:
                    for key in self.cornerTexts[2]:
                        self.cornerTexts[2][key]["text"] = ""
                    self.dicomVolumeNode = 0

            # Case II: Only background
            elif (backgroundVolume is not None):
                backgroundVolumeName = backgroundVolume.GetName()
                if self.bottomLeft:
                    self.cornerTexts[0]["3-Background"]["text"] = "B: " + backgroundVolumeName

                uids = backgroundVolume.GetAttribute("DICOM.instanceUIDs")
                if uids:
                    uid = uids.partition(" ")[0]
                    self.makeDicomAnnotation(uid, None, sliceViewName)
                    self.dicomVolumeNode = 1
                else:
                    self.dicomVolumeNode = 0

            # Case III: Only foreground
            elif (foregroundVolume is not None):
                if self.bottomLeft:
                    foregroundVolumeName = foregroundVolume.GetName()
                    self.cornerTexts[0]["2-Foreground"]["text"] = "F: " + foregroundVolumeName

                uids = foregroundVolume.GetAttribute("DICOM.instanceUIDs")
                if uids:
                    uid = uids.partition(" ")[0]
                    # passed UID as bg
                    self.makeDicomAnnotation(uid, None, sliceViewName)
                    self.dicomVolumeNode = 1
                else:
                    self.dicomVolumeNode = 0

            # Ensure visibility of top-right corner annotations if slab reconstruction is enabled
            # See https://github.com/Slicer/Slicer/issues/7092
            if sliceNode.GetSlabReconstructionEnabled() and self.allowForcingTopRightVisibility:
                self.topRight = 1
                self.topRightCheckBox.checked = True

                # Disable automatic enforcement to allow user-controlled visibility toggling.
                self.allowForcingTopRightVisibility = False

                # Omit saving the value in the settings because the top-right corner annotations
                # visibility was not expliitly toggled by the user.

            # Slab reconstruction is applied to both foreground and background
            if self.topRight and sliceNode.GetSlabReconstructionEnabled():
                unitNode = slicer.app.applicationLogic().GetSelectionNode().GetUnitNode("length")
                self.cornerTexts[3]["8-SlabReconstructionThickness"]["text"] = "Thickness: " + str(
                    sliceNode.GetSlabReconstructionThickness()) + " " + unitNode.GetSuffix()
                self.cornerTexts[3]["9-SlabReconstructionType"]["text"] = "Type: " + sliceNode.GetSlabReconstructionTypeAsString(
                    sliceNode.GetSlabReconstructionType())
            else:
                self.cornerTexts[3]["8-SlabReconstructionThickness"]["text"] = ""
                self.cornerTexts[3]["9-SlabReconstructionType"]["text"] = ""

            if (labelVolume is not None) and self.bottomLeft:
                labelOpacity = sliceCompositeNode.GetLabelOpacity()
                labelVolumeName = labelVolume.GetName()
                self.cornerTexts[0]["1-Label"]["text"] = "L: " + labelVolumeName + " (" + str(
                    "%d" % (labelOpacity * 100)) + "%)"

            self.drawCornerAnnotations(sliceViewName)

    def makeDicomAnnotation(self, bgUid, fgUid, sliceViewName):
        # Do not attempt to retrieve dicom values if no local database exists
        if not slicer.dicomDatabase.isOpen:
            return
        viewHeight = self.sliceViews[sliceViewName].height
        if fgUid is not None and bgUid is not None:
            backgroundDicomDic = self.extractDICOMValues(bgUid)
            foregroundDicomDic = self.extractDICOMValues(fgUid)
            # check if background and foreground are from different patients
            # and remove the annotations

            if self.topLeft and viewHeight > 150:
                if backgroundDicomDic["Patient Name"] != foregroundDicomDic["Patient Name"
                                                                            ] or backgroundDicomDic["Patient ID"] != foregroundDicomDic["Patient ID"
                                                                                                                                        ] or backgroundDicomDic["Patient Birth Date"] != foregroundDicomDic["Patient Birth Date"]:
                    for key in self.cornerTexts[2]:
                        self.cornerTexts[2][key]["text"] = ""
                else:
                    if "1-PatientName" in self.cornerTexts[2]:
                        self.cornerTexts[2]["1-PatientName"]["text"] = backgroundDicomDic["Patient Name"].replace("^", ", ")
                    if "2-PatientID" in self.cornerTexts[2]:
                        self.cornerTexts[2]["2-PatientID"]["text"] = "ID: " + backgroundDicomDic["Patient ID"]
                    backgroundDicomDic["Patient Birth Date"] = self.formatDICOMDate(backgroundDicomDic["Patient Birth Date"])
                    if "3-PatientInfo" in self.cornerTexts[2]:
                        self.cornerTexts[2]["3-PatientInfo"]["text"] = self.makePatientInfo(backgroundDicomDic)

                    if (backgroundDicomDic["Series Date"] != foregroundDicomDic["Series Date"]):
                        if "4-Bg-SeriesDate" in self.cornerTexts[2]:
                            self.cornerTexts[2]["4-Bg-SeriesDate"]["text"] = "B: " + self.formatDICOMDate(backgroundDicomDic["Series Date"])
                        if "5-Fg-SeriesDate" in self.cornerTexts[2]:
                            self.cornerTexts[2]["5-Fg-SeriesDate"]["text"] = "F: " + self.formatDICOMDate(foregroundDicomDic["Series Date"])
                    else:
                        if "4-Bg-SeriesDate" in self.cornerTexts[2]:
                            self.cornerTexts[2]["4-Bg-SeriesDate"]["text"] = self.formatDICOMDate(backgroundDicomDic["Series Date"])

                    if (backgroundDicomDic["Series Time"] != foregroundDicomDic["Series Time"]):
                        if "6-Bg-SeriesTime" in self.cornerTexts[2]:
                            self.cornerTexts[2]["6-Bg-SeriesTime"]["text"] = "B: " + self.formatDICOMTime(backgroundDicomDic["Series Time"])
                        if "7-Fg-SeriesTime" in self.cornerTexts[2]:
                            self.cornerTexts[2]["7-Fg-SeriesTime"]["text"] = "F: " + self.formatDICOMTime(foregroundDicomDic["Series Time"])
                    else:
                        if "6-Bg-SeriesTime" in self.cornerTexts[2]:
                            self.cornerTexts[2]["6-Bg-SeriesTime"]["text"] = self.formatDICOMTime(backgroundDicomDic["Series Time"])

                    if (backgroundDicomDic["Series Description"] != foregroundDicomDic["Series Description"]):
                        if "8-Bg-SeriesDescription" in self.cornerTexts[2]:
                            self.cornerTexts[2]["8-Bg-SeriesDescription"]["text"] = "B: " + backgroundDicomDic["Series Description"]
                        if "9-Fg-SeriesDescription" in self.cornerTexts[2]:
                            self.cornerTexts[2]["9-Fg-SeriesDescription"]["text"] = "F: " + foregroundDicomDic["Series Description"]
                    else:
                        if "8-Bg-SeriesDescription" in self.cornerTexts[2]:
                            self.cornerTexts[2]["8-Bg-SeriesDescription"]["text"] = backgroundDicomDic["Series Description"]

        # Only Background or Only Foreground
        else:
            uid = bgUid
            dicomDic = self.extractDICOMValues(uid)

            if self.topLeft and viewHeight > 150:
                self.cornerTexts[2]["1-PatientName"]["text"] = dicomDic["Patient Name"].replace("^", ", ")
                self.cornerTexts[2]["2-PatientID"]["text"] = "ID: " + dicomDic["Patient ID"]
                dicomDic["Patient Birth Date"] = self.formatDICOMDate(dicomDic["Patient Birth Date"])
                self.cornerTexts[2]["3-PatientInfo"]["text"] = self.makePatientInfo(dicomDic)
                self.cornerTexts[2]["4-Bg-SeriesDate"]["text"] = self.formatDICOMDate(dicomDic["Series Date"])
                self.cornerTexts[2]["6-Bg-SeriesTime"]["text"] = self.formatDICOMTime(dicomDic["Series Time"])
                self.cornerTexts[2]["8-Bg-SeriesDescription"]["text"] = dicomDic["Series Description"]

            # top right corner annotation would be hidden if view height is less than 260 pixels
            if (self.topRight):
                self.cornerTexts[3]["1-Institution-Name"]["text"] = dicomDic["Institution Name"]
                self.cornerTexts[3]["2-Referring-Phisycian"]["text"] = dicomDic["Referring Physician Name"].replace("^", ", ")
                self.cornerTexts[3]["3-Manufacturer"]["text"] = dicomDic["Manufacturer"]
                self.cornerTexts[3]["4-Model"]["text"] = dicomDic["Model"]
                self.cornerTexts[3]["5-Patient-Position"]["text"] = dicomDic["Patient Position"]
                modality = dicomDic["Modality"]
                if modality == "MR":
                    self.cornerTexts[3]["6-TR"]["text"] = "TR " + dicomDic["Repetition Time"]
                    self.cornerTexts[3]["7-TE"]["text"] = "TE " + dicomDic["Echo Time"]

    @staticmethod
    def makePatientInfo(dicomDic):
        # This will give an string of patient's birth date,
        # patient's age and sex
        patientInfo = dicomDic["Patient Birth Date"
                               ] + ", " + dicomDic["Patient Age"
                                                   ] + ", " + dicomDic["Patient Sex"]
        return patientInfo

    @staticmethod
    def formatDICOMDate(date):
        standardDate = ""
        if date != "":
            date = date.rstrip()
            # convert to ISO 8601 Date format
            standardDate = date[:4] + "-" + date[4:6] + "-" + date[6:]
        return standardDate

    @staticmethod
    def formatDICOMTime(time):
        if time == "":
            # time field is empty
            return ""
        studyH = time[:2]
        if int(studyH) > 12:
            studyH = str(int(studyH) - 12)
            clockTime = " PM"
        else:
            studyH = studyH
            clockTime = " AM"
        studyM = time[2:4]
        studyS = time[4:6]
        return studyH + ":" + studyM + ":" + studyS + clockTime

    @staticmethod
    def fitText(text, textSize):
        if len(text) > textSize:
            preSize = int(textSize / 2)
            postSize = preSize - 3
            text = text[:preSize] + "..." + text[-postSize:]
        return text

    def drawCornerAnnotations(self, sliceViewName):
        if not self.sliceViewAnnotationsEnabled:
            return
        # Auto-Adjust
        # adjust maximum text length based on fontsize and view width
        viewWidth = self.sliceViews[sliceViewName].width
        self.maximumTextLength = int((viewWidth - 40) / self.fontSize)

        for i, cornerText in enumerate(self.cornerTexts):
            keys = sorted(cornerText.keys())
            cornerAnnotation = ""
            for key in keys:
                text = cornerText[key]["text"]
                if (text != ""):
                    text = self.fitText(text, self.maximumTextLength)
                    # level 1: All categories will be displayed
                    if self.annotationsDisplayAmount == 0:
                        cornerAnnotation = cornerAnnotation + text + "\n"
                    # level 2: Category A and B will be displayed
                    elif self.annotationsDisplayAmount == 1:
                        if (cornerText[key]["category"] != "C"):
                            cornerAnnotation = cornerAnnotation + text + "\n"
                    # level 3 only Category A will be displayed
                    elif self.annotationsDisplayAmount == 2:
                        if (cornerText[key]["category"] == "A"):
                            cornerAnnotation = cornerAnnotation + text + "\n"
            sliceCornerAnnotation = self.sliceViews[sliceViewName].cornerAnnotation()
            sliceCornerAnnotation.SetText(i, cornerAnnotation)
            textProperty = sliceCornerAnnotation.GetTextProperty()
            textProperty.SetShadow(1)

        self.sliceViews[sliceViewName].scheduleRender()

    def resetTexts(self):
        for i, cornerText in enumerate(self.cornerTexts):
            for key in cornerText.keys():
                self.cornerTexts[i][key]["text"] = ""

    def extractDICOMValues(self, uid):

        # Used cached tags, if found.
        # DICOM objects are not allowed to be changed,
        # so if the UID matches then the content has to match as well
        if uid in self.extractedDICOMValuesCache.keys():
            return self.extractedDICOMValuesCache[uid]

        p = {}
        tags = {
            "0008,0021": "Series Date",
            "0008,0031": "Series Time",
            "0008,0060": "Modality",
            "0008,0070": "Manufacturer",
            "0008,0080": "Institution Name",
            "0008,0090": "Referring Physician Name",
            "0008,103e": "Series Description",
            "0008,1090": "Model",
            "0010,0010": "Patient Name",
            "0010,0020": "Patient ID",
            "0010,0030": "Patient Birth Date",
            "0010,0040": "Patient Sex",
            "0010,1010": "Patient Age",
            "0018,5100": "Patient Position",
            "0018,0080": "Repetition Time",
            "0018,0081": "Echo Time"
        }
        for tag in tags.keys():
            value = slicer.dicomDatabase.instanceValue(uid, tag)
            p[tags[tag]] = value

        # Store DICOM tags in cache
        self.extractedDICOMValuesCache[uid] = p
        if len(self.extractedDICOMValuesCache) > self.extractedDICOMValuesCacheSize:
            # cache is full, drop oldest item
            self.extractedDICOMValuesCache.popitem(last=False)

        return p
