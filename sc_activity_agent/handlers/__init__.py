"""Step executors: one function per plan step kind, each acting as the role and user the Runtime picks.
The package splits them by area (field work, checklists, review, invoices, proposals, notes); `make_handlers` composes them."""
import json

from . import checklists, field, invoices, notes, proposals, review
from .common import ACTION, Skip, cancel_wo, end_plan, insert_steps
from .guard import follow, guarded, preflight, watch
from .runtime import Runtime


def make_handlers(rt):
    def call(wo, step, method, path, **kw):
        app, user = rt.user_for(wo["location"], step["kind"], wo, step)
        return app.call(user, method, path, action=step["kind"], wo=wo["sc_id"], write=method != "GET", **kw)

    def ctx_of(wo):
        return json.loads(wo["ctx"])

    answer = checklists.build(rt, call, ctx_of)
    handlers = {**notes.build(rt, call, ctx_of), **field.build(rt, call, ctx_of, answer), **review.build(rt, call, ctx_of),
                **invoices.build(rt, call, ctx_of), **proposals.build(rt, call, ctx_of)}
    return {k: guarded(rt, call, k, f) for k, f in handlers.items()}
