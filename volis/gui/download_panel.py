"""The "Download a model" section of the developer Models page. What it decides is
in download.py; this paints it and runs scripts/fetch_model.py as a program of
its own. Volis itself stays offline, so nothing here imports a Hugging Face
library or opens a connection."""

from __future__ import annotations

import logging

from PySide6.QtCore import QProcess, QProcessEnvironment, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QComboBox, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QProgressBar,
    QPushButton, QVBoxLayout, QWidget,
)

from .. import download, models, paths

log = logging.getLogger(__name__)

OUTPUT_KEPT = 20_000  # characters of a program's output, for the reason it stopped
OPEN, CLOSED = "▾ Download a model", "▸ Download a model"


def _label(name: str = "muted") -> QLabel:
    label = QLabel()
    label.setObjectName(name)
    label.setWordWrap(True)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return label


def _say(label: QLabel, words: str, name: str = "muted") -> None:
    label.setText(words)
    label.setVisible(bool(words))
    if label.objectName() != name:
        label.setObjectName(name)
        label.style().unpolish(label)
        label.style().polish(label)


class DownloadPanel(QWidget):
    def __init__(self, root, rescan) -> None:
        super().__init__()
        self.root, self.rescan = root, rescan
        self.process: QProcess | None = None
        self.task = ""  # "" | "lookup" | "download"
        self.cancelled = False
        self.answer: download.Lookup | None = None
        self.chosen: download.Offer | None = None
        self.target = None
        self.wanted: list[str] = []
        self.out, self.err = "", ""

        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(8)
        self.toggle = QPushButton(CLOSED)
        self.toggle.clicked.connect(lambda: self.show_body(self.body.isHidden()))
        column.addWidget(self.toggle, 0, Qt.AlignmentFlag.AlignLeft)
        self.body = QWidget()
        self.body.hide()
        column.addWidget(self.body)
        lines = QVBoxLayout(self.body)
        lines.setContentsMargins(0, 0, 0, 0)
        lines.setSpacing(8)
        self.available = download.available(root)
        if not self.available:
            only_source = _label()
            only_source.setText("Downloading works only from the source folder. "
                                "To add a model here, copy its folder into models.")
            lines.addWidget(only_source)
            return
        self._build(lines)
        self._refresh()

    def _build(self, lines: QVBoxLayout) -> None:
        self.paste = QLineEdit()
        self.paste.setPlaceholderText("A Hugging Face link, or owner/name")
        self.paste.textEdited.connect(self._pasted)
        self.paste.returnPressed.connect(self.look_up)
        lines.addWidget(self.paste)

        roles = QHBoxLayout()
        self.roles = QButtonGroup(self)
        self.role_buttons: dict[str, QPushButton] = {}
        for role, words in download.ROLES.items():
            button = QPushButton(words)
            button.setCheckable(True)
            self.roles.addButton(button)
            self.role_buttons[role] = button
            button.toggled.connect(self._role_changed)
            roles.addWidget(button)
        roles.addStretch(1)
        self.look_up_button = QPushButton("Look up")
        self.look_up_button.clicked.connect(self.look_up)
        roles.addWidget(self.look_up_button)
        lines.addLayout(roles)

        self.access = QFrame()
        self.access.setFrameShape(QFrame.Shape.StyledPanel)
        access = QVBoxLayout(self.access)
        self.access_words = _label("problem")
        access.addWidget(self.access_words)
        buttons = QHBoxLayout()
        self.open_page = QPushButton("Open the model's page")
        self.open_page.clicked.connect(self._open_page)
        self.copy_login = QPushButton("Copy the command")
        self.copy_login.clicked.connect(lambda: QApplication.clipboard().setText(download.login_command()))
        buttons.addWidget(self.open_page)
        buttons.addWidget(self.copy_login)
        buttons.addStretch(1)
        access.addLayout(buttons)
        lines.addWidget(self.access)

        self.licence = _label()
        lines.addWidget(self.licence)
        self.notes = _label()
        lines.addWidget(self.notes)

        self.form_holder = QWidget()
        form = QFormLayout(self.form_holder)
        form.setContentsMargins(0, 0, 0, 0)
        self.version, self.encoder = QComboBox(), QComboBox()
        self.version.currentIndexChanged.connect(self._refresh)
        self.encoder.currentIndexChanged.connect(self._refresh)
        self.folder, self.display_name = QLineEdit(), QLineEdit()
        self.display_name.setPlaceholderText("Optional: the name shown in the lists")
        self.folder.textEdited.connect(self._refresh)
        self.files = _label()
        form.addRow("Version", self.version)
        form.addRow("Audio encoder", self.encoder)
        form.addRow("Files", self.files)
        form.addRow("Folder", self.folder)
        form.addRow("Name", self.display_name)
        self.form = form
        lines.addWidget(self.form_holder)

        self.summary = _label()
        lines.addWidget(self.summary)
        actions = QHBoxLayout()
        self.download_button = QPushButton("Download")
        self.download_button.clicked.connect(self.start_download)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.cancel)
        actions.addWidget(self.download_button)
        actions.addWidget(self.cancel_button)
        actions.addStretch(1)
        lines.addLayout(actions)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setRange(0, 1000)
        lines.addWidget(self.bar)
        self.status = _label()
        lines.addWidget(self.status)

    # -------------------------------------------------------------- what is shown

    def show_body(self, shown: bool) -> None:
        self.body.setVisible(shown)
        self.toggle.setText(OPEN if shown else CLOSED)

    def role(self) -> str:
        return next((role for role, button in self.role_buttons.items() if button.isChecked()), "")

    def busy(self) -> bool:
        return bool(self.task)

    def _pasted(self) -> None:
        self.answer = self.chosen = None
        _say(self.status, "")
        self._refresh()

    def _role_changed(self, checked: bool) -> None:
        if checked:  # the file list is already here: no need to go online for this
            self._fill_offer()
            self._refresh()

    def _fill_offer(self) -> None:
        self.chosen = None
        if self.answer is None or not self.role():
            return
        self.chosen = download.offer(self.answer.files, self.role())
        self._fill_combo(self.version, self.chosen.versions, "Choose a version",
                         lambda v: f"{v.label}, {download.size_words(v.size)}", lambda v: v.usable)
        self._fill_combo(self.encoder, self.chosen.encoders, "Choose an audio encoder",
                         lambda e: f"{e.name}, {download.size_words(e.size)}", lambda e: True)
        if not self.folder.text():
            self.folder.setText(self.answer.repo.split("/")[-1])

    def _fill_combo(self, combo: QComboBox, items: list, prompt: str, words, usable) -> None:
        combo.blockSignals(True)
        combo.clear()
        if len(items) != 1:
            combo.addItem(prompt, None)
        for item in items:
            combo.addItem(words(item), item)
            if not usable(item):
                combo.model().item(combo.count() - 1).setEnabled(False)
        combo.setCurrentIndex(0)
        combo.blockSignals(False)

    def _refresh(self, *_) -> None:
        looked = self.answer is not None and not self.answer.error
        locked = self.task == "download"
        needs_access = looked and self.answer.gated and not self.answer.can_download
        self.access.setVisible(needs_access)
        if needs_access:
            steps = download.access_steps(self.answer.repo)
            self.access_words.setText("You don't have access to this model yet.\n"
                                      + "\n".join(f"{i}. {step}" for i, step in enumerate(steps, 1)))
        licence, warned = download.license_line(self.answer.license) if looked else ("", False)
        _say(self.licence, licence, "problem" if warned else "muted")
        chosen = self.chosen if looked else None
        _say(self.notes, "\n".join(chosen.notes) if chosen else "")
        self.form_holder.setVisible(chosen is not None)
        for field, shown in ((self.version, chosen is not None and bool(chosen.versions)),
                             (self.encoder, chosen is not None and len(chosen.encoders) > 1)):
            self.form.setRowVisible(field, shown)

        self.wanted, self.target, need, problem = [], None, 0, ""
        if chosen is not None:
            self.wanted = download.selection(chosen, self.version.currentData(), self.encoder.currentData())
            name = self.folder.text()
            problem = download.folder_problem(self.root, self.role(), name)
            if not problem:
                self.target = download.target_folder(self.root, self.role(), name)
                missing = download.to_fetch(self.target, self.answer.files, self.wanted)
                need = sum(missing.values())
                problem = download.space_problem(need, download.free_on(self.target), self.target)
                self.nothing_missing = not missing
            self.files.setText(_files_words(self.wanted))
            settled = self.target is not None and download.name_is_settled(self.target)
            self.display_name.setEnabled(not settled and not locked)
            self.display_name.setPlaceholderText("This folder already has its name" if settled
                                                 else "Optional: the name shown in the lists")
        ready = bool(self.wanted) and self.target is not None and not problem and not needs_access
        if ready:
            words = ("Everything is already here." if self.nothing_missing
                     else f"To download: {download.size_words(need)}, into {self.target}")
            _say(self.summary, words)
        else:
            _say(self.summary, problem, "problem")

        self.look_up_button.setEnabled(not self.task and bool(self.role()) and download.repo_id(self.paste.text()) is not None)
        self.paste.setEnabled(not self.task)
        for button in self.role_buttons.values():
            button.setEnabled(not locked)
        for field in (self.version, self.encoder, self.folder):
            field.setEnabled(not locked)
        self.download_button.setVisible(chosen is not None)
        self.download_button.setEnabled(ready and not self.task and not self.nothing_missing)
        self.cancel_button.setVisible(bool(self.task))
        self.bar.setVisible(locked)

    def _open_page(self) -> None:
        if self.answer is not None:
            QDesktopServices.openUrl(QUrl(f"https://huggingface.co/{self.answer.repo}"))

    # -------------------------------------------------------------- running the program

    def _start(self, task: str, command: list[str]) -> None:
        self.task, self.cancelled, self.out, self.err = task, False, "", ""
        process = QProcess(self)
        environment = QProcessEnvironment.systemEnvironment()
        for name in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE"):  # only for this program; Volis keeps them
            environment.remove(name)
        environment.insert("PYTHONUTF8", "1")
        process.setProcessEnvironment(environment)
        process.setWorkingDirectory(str(self.root))
        process.readyReadStandardOutput.connect(self._read_out)
        process.readyReadStandardError.connect(self._read_err)
        process.finished.connect(self._finished)
        process.errorOccurred.connect(self._failed_to_start)
        self.process = process
        log.info("download panel: %s", " ".join(command))
        process.start(command[0], command[1:])
        self._refresh()

    def _read_out(self) -> None:
        self.out += bytes(self.process.readAllStandardOutput()).decode("utf-8", "replace")
        lines = self.out.split("\n")
        self.out = "\n".join(lines[-1:] if self.task == "download" else lines)[-OUTPUT_KEPT:]
        if self.task == "download":
            for line in lines[:-1]:
                if progress := download.read_progress(line):
                    done, total = progress
                    self.bar.setValue(done * 1000 // total if total else 0)
                    _say(self.status, download.progress_words(done, total))

    def _read_err(self) -> None:
        self.err = (self.err + bytes(self.process.readAllStandardError()).decode("utf-8", "replace"))[-OUTPUT_KEPT:]

    def _failed_to_start(self, error) -> None:
        if error == QProcess.ProcessError.FailedToStart:
            task, self.task = self.task, ""
            log.warning("download panel: could not start %s: %s", task, self.process.errorString())
            _say(self.status, f"Couldn't start the downloader: {self.process.errorString()}", "problem")
            self._refresh()

    def _finished(self, code: int, _status) -> None:
        self._read_out()
        self._read_err()
        task, self.task = self.task, ""
        self.process.deleteLater()
        self.process = None
        if not task:
            return
        if task == "lookup":
            self._looked_up()
        else:
            self._downloaded(code)
        self._refresh()

    def look_up(self) -> None:
        repo = download.repo_id(self.paste.text())
        if self.task or repo is None or not self.role():
            return
        self.answer = self.chosen = None
        self.folder.clear()
        self.display_name.clear()
        _say(self.status, "Looking it up...")
        self._start("lookup", download.lookup_command(self.root, repo))

    def _looked_up(self) -> None:
        if self.cancelled:
            _say(self.status, "")
            return
        self.answer = download.read_lookup(download.repo_id(self.paste.text()) or "", self.out)
        problem = download.lookup_problem(self.answer)
        _say(self.status, problem, "problem" if problem else "muted")
        self._fill_offer()

    def start_download(self) -> None:
        if self.task or not self.wanted or self.target is None:
            return
        name = "" if download.name_is_settled(self.target) else self.display_name.text()
        self.bar.setValue(0)
        _say(self.status, "Starting...")
        self.show_body(True)
        self._started_target, self._started_wanted = self.target, list(self.wanted)
        self._start("download", download.download_command(self.root, self.answer.repo, self.role(), self.folder.text(),
                                                          self.wanted, name))

    def _downloaded(self, code: int) -> None:
        target, wanted = self._started_target, self._started_wanted
        if self.cancelled:
            download.remove_leftovers(target)
            _say(self.status, "Cancelled. Files that finished are kept; the one under way will start again next time.")
            return
        if code != 0:
            _say(self.status, download.problem_in(self.err or self.out), "problem")
            return
        role = self.role()
        if role == "mt":
            found = models.discover_translators(paths.mt_dir(self.root))
        else:
            directory = paths.asr_dir(self.root) if role == "asr" else paths.tts_dir(self.root)
            found = models.discover(directory, models.Role.ASR if role == "asr" else models.Role.TTS)
        words, worked = download.finished_words(target, wanted, found)
        log.info("download panel: %s", words)
        self.rescan()
        _say(self.status, words, "status" if worked else "problem")

    def cancel(self) -> None:
        if self.process is not None:
            self.cancelled = True
            self.process.kill()

    # -------------------------------------------------------------- closing the window

    def may_close(self) -> bool:
        """Asked before the window closes, so a click by mistake loses nothing."""
        if self.task != "download":
            return True
        return self._ask_to_close()

    def _ask_to_close(self) -> bool:
        answer = QMessageBox.question(self.window(), "Volis", "A model is still downloading. Stop it and close Volis?\n"
                                      "Files that finished are kept; the one under way will start again next time.")
        return answer == QMessageBox.StandardButton.Yes

    def shutdown(self) -> None:
        if self.process is None:
            return
        task, self.task = self.task, ""
        self.process.kill()
        self.process.waitForFinished(5000)
        if task == "download":
            download.remove_leftovers(self._started_target)


def _files_words(names: list[str]) -> str:
    if not names:
        return ""
    if len(names) <= 6:
        return ", ".join(names)
    return f"{', '.join(names[:5])} and {len(names) - 5} more"
