from pi_kiosk.host import Host
from pi_kiosk.steps.autologin import AutologinStep
from pi_kiosk.steps.final_action import FinalActionStep
from pi_kiosk.steps.nosleep import NoSleepStep
from pi_kiosk.steps.project_kiosk import ProjectKioskStep
from pi_kiosk.steps.register_totem import RegisterTotemStep
from pi_kiosk.steps.rotation import RotationStep
from pi_kiosk.steps.rustdesk import RustDeskStep
from pi_kiosk.steps.save_state import SaveStateStep
from pi_kiosk.steps.setup_summary import SetupSummaryStep
from pi_kiosk.steps.touch import TouchStep
from pi_kiosk.ui import UI
from pi_kiosk.wizard_context import WizardContext


class NotARaspberryPi(RuntimeError):
    """The wizard must not mutate a non-Pi machine."""


class NeedRoot(RuntimeError):
    """raspi-config and system files need root."""


def default_steps(host: Host | None = None):
    return (
        RotationStep(),
        TouchStep(),
        NoSleepStep(),
        AutologinStep(),
        RustDeskStep(),
        ProjectKioskStep(prompt_for_next_action=False),
        SaveStateStep(),
        RegisterTotemStep(),
        SetupSummaryStep(),
        FinalActionStep(),
    )


class Wizard:
    def __init__(self, host: Host, ui: UI, steps=None) -> None:
        self.host = host
        self.ui = ui
        self.steps = tuple(steps) if steps is not None else default_steps(host)

    @classmethod
    def question_step_ids(cls) -> list[str]:
        return [
            step.id
            for step in default_steps()
            if getattr(step, "interactive", bool(step.choices))
        ]

    def run(self) -> list[str]:
        """Ask every question first, so a bad answer cannot leave a half-configured Pi.

        Steps marked `ask_after_apply` (the final action) are asked once the
        summary has been shown, as before.
        """
        self._check_guards()
        context = WizardContext(host=self.host, ui=self.ui)
        upfront = []
        for step in self.steps:
            if getattr(step, "ask_after_apply", False):
                break
            upfront.append(step)
        for step in upfront:
            context.record_answer(step.id, step.ask(self.ui, context))

        reports = self._apply(upfront, context)
        for step in self.steps[len(upfront):]:
            context.record_answer(step.id, step.ask(self.ui, context))
            reports += self._apply([step], context)
        return reports

    def apply_answers(self, answers: dict) -> list[str]:
        """Apply answers collected elsewhere (the visual wizard) without asking anything."""
        self._check_guards()
        context = WizardContext(host=self.host, ui=self.ui)
        for step in self.steps:
            if step.id in answers:
                context.record_answer(step.id, answers[step.id])
        return self._apply(self.steps, context)

    def _check_guards(self) -> None:
        if not self.host.is_raspberry_pi():
            raise NotARaspberryPi(
                "This tool only configures Raspberry Pi OS. "
                "Nothing was changed on this machine."
            )
        if not self.host.is_root():
            raise NeedRoot("Run this tool with sudo. Nothing was changed.")
        self.host.user()

    def _apply(self, steps, context: WizardContext) -> list[str]:
        reports: list[str] = []
        for step in steps:
            try:
                report = step.apply(self.host, context.answer(step.id), context)
            except Exception:
                if step.id == ProjectKioskStep.id:
                    self._register_after_content_failure(context)
                raise
            context.record_report(report)
            self.ui.info(report)
            reports.append(report)
        return reports

    def _register_after_content_failure(self, context: WizardContext) -> None:
        """Like Windows: a failed download must not also lose the totem registration."""
        if context.answer(RegisterTotemStep.id) is None:
            return
        register = next((step for step in self.steps if step.id == RegisterTotemStep.id), None)
        if register is None:
            return
        self.ui.warn("Kiosk content failed. Attempting to register the totem anyway.")
        try:
            self.ui.info(register.apply(self.host, context.answer(RegisterTotemStep.id), context))
        except Exception:
            self.ui.warn(
                "Totem registration or status setup failed; retry it when the connection is available."
            )
