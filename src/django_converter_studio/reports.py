"""Telling an admin user (Django's or Wagtail's) how a batch of conversions went."""

from __future__ import annotations

import posixpath
from collections.abc import Iterable

from django.contrib import messages
from django.http import HttpRequest
from django.utils.translation import gettext as _
from django.utils.translation import ngettext

from .models import ConversionJob

Status = ConversionJob.Status


def report(request: HttpRequest, jobs: Iterable[ConversionJob], *, nothing: str) -> None:
    """Messages for the user: what was converted and its cost, what was queued, and for every
    failure the API's own reason."""
    jobs = list(jobs)
    if not jobs:
        messages.info(request, nothing)
        return
    done = [job for job in jobs if job.status == Status.DONE]
    queued = [job for job in jobs if job.status in (Status.QUEUED, Status.RUNNING)]
    if done:
        credits = sum(job.credits or 0 for job in done)
        messages.success(
            request,
            ngettext(
                "Converted %(count)d file (%(credits)d credits).",
                "Converted %(count)d files (%(credits)d credits).",
                len(done),
            )
            % {"count": len(done), "credits": credits},
        )
    if queued:
        messages.info(
            request,
            ngettext(
                "%(count)d file is being converted in the background.",
                "%(count)d files are being converted in the background.",
                len(queued),
            )
            % {"count": len(queued)},
        )
    for job in jobs:
        name = posixpath.basename(job.source_name)
        if job.status == Status.FAILED:
            messages.error(
                request,
                _("%(file)s was not converted: %(reason)s")
                % {"file": name, "reason": job.error_message},
            )
        elif job.status == Status.SKIPPED:
            messages.warning(
                request,
                _("%(file)s was skipped: %(reason)s") % {"file": name, "reason": job.error_message},
            )
