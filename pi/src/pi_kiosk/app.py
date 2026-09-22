from pi_kiosk.host import Host
from pi_kiosk.steps.autologin import AutologinStep
from pi_kiosk.steps.final_action import FinalActionStep
from pi_kiosk.steps.nosleep import NoSleepStep
from pi_kiosk.steps.project_kiosk import ProjectKioskStep
from pi_kiosk.steps.register_totem import RegisterTotemStep
from pi_kiosk.steps.rotation import RotationStep
from pi_kiosk.steps.rustdesk import RustDeskStep
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
        if not self.host.is_raspberry_pi():
            raise NotARaspberryPi(
                "This tool only configures Raspberry Pi OS. "
                "Nothing was changed on this machine."
            )
        if not self.host.is_root():
            raise NeedRoot("Run this tool with sudo. Nothing was changed.")
        self.host.user()

        context = WizardContext(host=self.host, ui=self.ui)
        reports: list[str] = []
        for step in self.steps:
            answer = step.ask(self.ui, context)
            context.record_answer(step.id, answer)
            report = step.apply(self.host, answer, context)
            context.record_report(report)
            self.ui.info(report)
            reports.append(report)
        return reports
