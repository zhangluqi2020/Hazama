import PySide.QtCore
from PySide.QtGui import *
from PySide.QtCore import *
from hazama.ui.editor_ui import Ui_editor
from hazama.ui.customobjects import TagCompleter, NGraphicsDropShadowEffect
from hazama.ui.customwidgets import DateTimeDialog
from hazama.ui import (font, datetimeTrans, currentDatetime, fullDatetimeFmt,
                       saveWidgetGeo, restoreWidgetGeo, datetimeToQt, DB_DATETIME_FMT_QT,
                       winDwmExtendWindowFrame, scaleRatio)
from hazama.config import settings, db, isWin, isWin10, isWin8, isWin7

# TODO: editor in the main window (no tabs)


class Editor(QFrame, Ui_editor):
    """The widget that used to edit diary's body, title, tag and datetime.
    Signal closed: (diaryId, needSave)
    """
    closed = Signal(int, bool)

    def __init__(self, diaryDict, parent=None):
        super().__init__(parent)
        self._saveOnClose = True
        self.setupUi(self)
        self.readOnly = self.datetime = self.id = self.timeModified = self.tagModified = None
        restoreWidgetGeo(self, settings['Editor'].get('windowGeo'))

        self.titleEditor.setFont(font.title)
        self.titleEditor.returnPressed.connect(
            lambda: None if self.readOnly else self.textEditor.setFocus())
        self.textEditor.setFont(font.text)
        self.textEditor.setAutoIndent(settings['Editor'].getboolean('autoIndent'))
        self.textEditor.setTabChangesFocus(not settings['Editor'].getboolean('tabIndent'))

        self.dtBtn.setFont(font.datetime)
        sz = max(font.datetime_m.ascent(), 12)
        self.dtBtn.setIconSize(QSize(sz, sz))
        self.lockBtn.setIconSize(QSize(sz, sz))
        self.lockBtn.clicked.connect(lambda: self.setReadOnly(False))

        self.tagEditor.setTextMargins(QMargins(2, 0, 2, 0))
        self.tagEditor.setCompleter(TagCompleter(list(db.get_tags()), self.tagEditor))
        self.tagEditor.returnPressed.connect(
            lambda: None if self.readOnly else self.box.button(QDialogButtonBox.Save).setFocus())

        if isWin10 and settings['Main'].getboolean('extendTitleBarBg'):
            self.bottomArea.setProperty('bgType', 'win10')

        # setup shortcuts
        # seems PySide has problem with QKeySequence.StandardKeys
        self.closeSaveSc = QShortcut(QKeySequence.Save, self, self.close)
        self.closeNoSaveSc = QShortcut(QKeySequence('Ctrl+W'), self, self.closeNoSave)
        self.quickCloseSc = QShortcut(QKeySequence('Esc'), self, self.closeNoSave)
        # Ctrl+Shift+Backtab doesn't work
        self.preSc = QShortcut(QKeySequence('Ctrl+Shift+Tab'), self)
        self.quickPreSc = QShortcut(QKeySequence('Left'), self)
        self.nextSc = QShortcut(QKeySequence('Ctrl+Tab'), self)
        self.quickNextSc = QShortcut(QKeySequence('Right'), self)

        self.fromDiaryDict(diaryDict)

    def showEvent(self, event):
        self._applyExtendTitleBarBg()
        if settings['Editor'].getboolean('titleFocus'):
            self.titleEditor.setCursorPosition(0)
        else:
            self.textEditor.setFocus()
            self.textEditor.moveCursor(QTextCursor.Start)

    # disable winEvent hack if PySide version doesn't support it
    if hasattr(PySide.QtCore, 'MSG') and hasattr(MSG, 'lParam'):
        def winEvent(self, msg):
            """See MainWindow.winEvent."""
            if msg.message == 0x0084:
                pos = QPoint(msg.lParam & 0xFFFF, msg.lParam >> 16)
                widget = self.childAt(self.mapFromGlobal(pos))
                if widget is self.bottomArea:
                    return True, 2
                else:
                    return False, 0
            else:
                return False, 0

    def closeEvent(self, event):
        """Normal close will save diary. For cancel operation, call closeNoSave."""
        settings['Editor']['windowGeo'] = saveWidgetGeo(self)
        self.closed.emit(self.id, self.needSave() if self._saveOnClose else False)
        event.accept()

    def mousePressEvent(self, event):
        """Handle mouse back/forward button"""
        if event.button() == Qt.XButton1:  # back
            self.preSc.activated.emit()
            event.accept()
        elif event.button() == Qt.XButton2:  # forward
            self.nextSc.activated.emit()
            event.accept()
        else:
            super().mousePressEvent(event)

    def _applyExtendTitleBarBg(self):
        if isWin and settings['Main'].getboolean('extendTitleBarBg'):
            winDwmExtendWindowFrame(self.winId(), bottom=self.bottomArea.height())
            self.setAttribute(Qt.WA_TranslucentBackground)

            if not isWin8:
                for i in (self.dtBtn, self.lockBtn):
                    eff = NGraphicsDropShadowEffect(5 if isWin7 else 3, i)
                    eff.setColor(QColor(Qt.white))
                    eff.setOffset(0, 0)
                    eff.setBlurRadius((16 if isWin7 else 8) * scaleRatio)
                    i.setGraphicsEffect(eff)

    def closeNoSave(self):
        self._saveOnClose = False
        self.close()

    def needSave(self):
        return (self.textEditor.document().isModified() or
                self.titleEditor.isModified() or self.timeModified or
                self.tagModified)

    def setReadOnly(self, readOnly):
        for i in [self.titleEditor, self.textEditor, self.tagEditor]:
            i.setReadOnly(readOnly)
        self.dtBtn.setCursor(Qt.ArrowCursor if readOnly else Qt.PointingHandCursor)
        self.box.setStandardButtons(self.box.Close if readOnly else
                                    self.box.Save | self.box.Cancel)
        self.box.button(self.box.Close if readOnly else self.box.Save).setDefault(True)
        self.lockBtn.setVisible(readOnly)
        self.titleEditor.setVisible(not readOnly or bool(self.titleEditor.text()))
        self.tagEditor.setVisible(not readOnly or bool(self.tagEditor.text()))
        for i in [self.quickCloseSc, self.quickPreSc, self.quickNextSc]:
            i.setEnabled(readOnly)
        self.readOnly = readOnly

        if isWin and settings['Main'].getboolean('extendTitleBarBg'):
            winDwmExtendWindowFrame(self.winId(), bottom=self.bottomArea.height())

    def fromDiaryDict(self, dic):
        self.timeModified = self.tagModified = False
        self.id = dic['id']
        self.datetime = dic.get('datetime')

        self.dtBtn.setText(datetimeTrans(self.datetime) if self.datetime else '')
        self.titleEditor.setText(dic.get('title', ''))
        self.tagEditor.setText(dic.get('tags', ''))
        self.textEditor.setRichText(dic.get('text', ''), dic.get('formats'))
        # if title is empty, use datetime instead. if no datetime (new), use "New Diary"
        t = (dic.get('title') or
             (datetimeTrans(self.datetime, stripTime=True) if 'datetime' in dic else None) or
             self.tr('New Diary'))
        self.setWindowTitle("%s - Hazama" % t)

        readOnly = (settings['Editor'].getboolean('autoReadOnly') and
                    self.datetime is not None and
                    datetimeToQt(self.datetime).daysTo(QDateTime.currentDateTime()) > 3)
        self.setReadOnly(readOnly)

    def toDiaryDict(self):
        text, formats = self.textEditor.getRichText()
        tags = self.tagEditor.text()
        if self.tagModified:  # remove duplicate tags
            tags = ' '.join(set(tags.split()))
        return dict(id=self.id, datetime=self.datetime or currentDatetime(),
                    text=text, formats=formats, title=self.titleEditor.text(),
                    tags=tags)

    @Slot()
    def on_tagEditor_textEdited(self):
        # tagEditor.isModified() will be reset by completer. So this instead.
        self.tagModified = True

    @Slot()
    def on_dtBtn_clicked(self):
        """Show datetime edit dialog"""
        if self.readOnly: return
        dtStr = currentDatetime() if self.datetime is None else self.datetime
        newDt = DateTimeDialog.getDateTime(datetimeToQt(dtStr), fullDatetimeFmt, self)
        if newDt is not None:
            newDtStr = newDt.toString(DB_DATETIME_FMT_QT)
            if newDtStr != self.datetime:
                self.datetime = newDtStr
                self.dtBtn.setText(datetimeTrans(newDtStr))
                self.timeModified = True
