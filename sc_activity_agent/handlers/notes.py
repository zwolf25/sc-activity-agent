"""Notes by either role, and the Subscriber's cancel step."""
import json

from .. import content
from .common import cancel_wo


def build(rt, call, ctx_of):
    def note(role):
        def run(engine, wo, step):
            situation = json.loads(step["payload"])["situation"]
            text = content.note(role, situation, ctx_of(wo), rt.rng)
            call(wo, step, "POST", f"/workorders/{wo['sc_id']}/notes",
                 body={"Note": text, "NotifyFollowers": False, "DoNotSendEmail": True})
        return run

    def cancel(engine, wo, step):
        cancel_wo(rt, wo, content.note("subscriber", json.loads(step["payload"])["situation"], ctx_of(wo), rt.rng))

    return {"prov_note": note("provider"), "sub_note": note("subscriber"), "cancel": cancel}
