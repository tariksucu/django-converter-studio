"""Converting an object's files by its rules: creating the conversions, running and queueing them.

Every conversion is a row of :class:`~django_converter_studio.models.ConversionJob`. A run reads
the file through its field's storage, uploads it, waits for the result and saves it through
storage again; the row keeps the API's conversion id as soon as it exists, so a run that is
repeated (a worker that died, a retry) picks the same conversion up instead of paying twice.
"""

from __future__ import annotations

import logging
import posixpath
from collections.abc import Iterable, Sequence
from contextlib import ExitStack
from datetime import timedelta
from functools import partial
from typing import Any

from converter_studio import (
    APIConnectionError,
    APIError,
    APITimeoutError,
    ConfirmationRequiredError,
    ConflictError,
    Conversion,
    ConversionFailedError,
    ConversionTimeoutError,
    ConverterStudio,
    ConverterStudioError,
    MissingApiKeyError,
    NotFoundError,
)
from django.contrib.contenttypes.models import ContentType
from django.db import models, transaction
from django.db.models import F, Q
from django.db.models.fields.files import FieldFile
from django.utils import timezone

from . import conf, services, tasks
from .client import open_client, require_api_key
from .models import ConversionJob
from .rules import Rule, get_rule, rules_for
from .signals import file_converted

logger = logging.getLogger("django_converter_studio")

Status = ConversionJob.Status
#: A conversion still "running" after this long is taken to have died with its process.
STUCK_AFTER = timedelta(hours=1)
#: Statuses after which the API's conversion cannot be picked up again.
_GONE = frozenset({"failed", "expired", "canceled"})


class _SourceError(Exception):
    """The source file could not be read through its storage."""


class _StorageError(Exception):
    """The result could not be saved through storage."""


# Choosing what to convert


def _target_filled(instance: models.Model, target: str) -> bool:
    value = getattr(instance, target, None)
    if isinstance(value, FieldFile):
        return bool(value.name)
    return bool(value)


def matching_rules(
    instance: models.Model, *, fields: Iterable[str] | None = None, force: bool = False
) -> list[Rule]:
    """The rules that would convert ``instance``'s files now. A target that is filled already is
    skipped unless ``force``; a file is replaced by its first matching replacing rule only."""
    wanted = set(fields) if fields is not None else None
    replaced: set[str] = set()
    chosen = []
    for rule in rules_for(type(instance)):
        if wanted is not None and rule.field not in wanted:
            continue
        value = getattr(instance, rule.field, None)
        if not isinstance(value, FieldFile) or not value.name or not rule.matches(value.name):
            continue
        if rule.replaces:
            if rule.field in replaced:
                continue
            replaced.add(rule.field)
        elif not force and rule.target and _target_filled(instance, rule.target):
            continue
        chosen.append(rule)
    return chosen


def mode(rule: Rule, run: str | None = None) -> str:
    """``"inline"`` or ``"task"``: how a rule's conversion runs (``"task"`` needs a framework)."""
    wanted = run or rule.run or conf.run_mode()
    if wanted in ("auto", "task"):
        return "task" if tasks.available() else "inline"
    return "inline"


def _content_type(instance: models.Model, using: str | None) -> ContentType:
    return ContentType.objects.db_manager(using).get_for_model(instance, for_concrete_model=False)


def create_jobs(
    instance: models.Model, rules: Sequence[Rule], *, using: str | None = None
) -> list[ConversionJob]:
    """A queued conversion for each rule, unless the same file is being converted already."""
    content_type = _content_type(instance, using)
    stuck = timezone.now() - STUCK_AFTER
    created = []
    for rule in rules:
        value = getattr(instance, rule.field)
        open_jobs = ConversionJob.objects.using(using).filter(
            Q(status=Status.QUEUED) | Q(status=Status.RUNNING, started_at__gte=stuck),
            content_type=content_type,
            object_id=str(instance.pk),
            rule=rule.name,
            source_name=value.name,
        )
        if open_jobs.exists():
            continue
        created.append(
            ConversionJob.objects.using(using).create(
                content_type=content_type,
                object_id=str(instance.pk),
                field=rule.field,
                rule=rule.name,
                source_name=value.name,
                to_format=rule.to,
                target=rule.target or "",
            )
        )
    return created


def _dispatch(
    jobs: Sequence[ConversionJob],
    instance: models.Model,
    run: str | None,
    using: str | None,
    now: bool,
) -> None:
    rules = {rule.name: rule for rule in rules_for(type(instance))}
    inline = [str(job.pk) for job in jobs if mode(rules[job.rule], run) == "inline"]
    queued = [str(job.pk) for job in jobs if str(job.pk) not in inline]
    if inline:
        if now:
            run_jobs(inline, instance=instance)
        else:
            # After the save is committed (at once outside a transaction); an error in a
            # conversion is recorded, never raised into the request that saved the object.
            transaction.on_commit(
                partial(run_jobs, inline, instance=instance), using=using, robust=True
            )
    if queued:
        transaction.on_commit(partial(enqueue, queued), using=using, robust=True)


def schedule(
    instance: models.Model,
    *,
    fields: Iterable[str] | None = None,
    force: bool = False,
    run: str | None = None,
    using: str | None = None,
) -> list[ConversionJob]:
    """Creates the conversions of ``instance``'s files and runs or queues them once the current
    transaction commits (what the ``post_save`` hook does for new uploads)."""
    jobs = create_jobs(instance, matching_rules(instance, fields=fields, force=force), using=using)
    if jobs:
        _dispatch(jobs, instance, run, using, now=False)
    return jobs


def convert_instance(
    instance: models.Model,
    *,
    fields: Iterable[str] | None = None,
    force: bool = False,
    run: str | None = None,
) -> list[ConversionJob]:
    """Converts ``instance``'s files by its rules: inline conversions run now and come back
    finished, task conversions are queued (after the current transaction commits). Used by the
    admin action, the management command and :meth:`ConverterStudioMixin.convert_files`."""
    using = instance._state.db
    jobs = create_jobs(instance, matching_rules(instance, fields=fields, force=force), using=using)
    if not jobs:
        return []
    _dispatch(jobs, instance, run, using, now=True)
    return list(ConversionJob.objects.using(using).filter(pk__in=[job.pk for job in jobs]))


def enqueue(job_ids: Sequence[str]) -> None:
    """Hands conversions to the tasks framework (inline when there is none)."""
    task = tasks.get_task()
    if task is None:
        run_jobs(job_ids)
        return
    try:
        task.enqueue(list(job_ids))
    except Exception as error:
        logger.exception("Converter Studio: could not queue conversions %s", list(job_ids))
        ConversionJob.objects.filter(pk__in=job_ids, status=Status.QUEUED).update(
            status=Status.FAILED,
            error_code="taskError",
            error_message=f"The conversion could not be queued: {error}",
            finished_at=timezone.now(),
        )


def retry(jobs: Iterable[ConversionJob], *, approve: bool = False) -> list[str]:
    """Runs failed or skipped conversions again (inline). ``approve`` goes ahead with those that
    cost more than their ``max_credits`` (``confirmationRequired``)."""
    ids = []
    stuck = timezone.now() - STUCK_AFTER
    for job in jobs:
        if job.status in (Status.FAILED, Status.SKIPPED) or (
            job.status == Status.RUNNING and job.started_at is not None and job.started_at < stuck
        ):
            ConversionJob.objects.filter(pk=job.pk).update(status=Status.QUEUED)
            ids.append(str(job.pk))
    return run_jobs(ids, approve=approve) if ids else []


# Running


def run_jobs(
    job_ids: Sequence[str], *, instance: models.Model | None = None, approve: bool = False
) -> list[str]:
    """Runs queued conversions (by id) one after the other and returns their statuses. Those that
    write into another field run before one that replaces the file they read."""
    order = {str(job_id): n for n, job_id in enumerate(job_ids)}
    jobs = sorted(
        ConversionJob.objects.filter(pk__in=list(job_ids)).select_related("content_type"),
        key=lambda job: (job.target == "", order.get(str(job.pk), 0)),
    )
    statuses = []
    with ExitStack() as stack:
        clients: list[ConverterStudio] = []

        def client() -> ConverterStudio:
            if not clients:
                require_api_key()
                clients.append(stack.enter_context(open_client()))
            return clients[0]

        for job in jobs:
            statuses.append(_run(job, instance, client, approve))
    return statuses


def _claim(job: ConversionJob) -> bool:
    now = timezone.now()
    claimed = (
        ConversionJob.objects.filter(pk=job.pk)
        .filter(
            Q(status=Status.QUEUED) | Q(status=Status.RUNNING, started_at__lt=now - STUCK_AFTER)
        )
        .update(
            status=Status.RUNNING,
            started_at=now,
            attempts=F("attempts") + 1,
            error_code="",
            error_message="",
        )
    )
    if claimed:
        job.status, job.started_at = Status.RUNNING, now
    return bool(claimed)


def _finish(
    job: ConversionJob, status: str, code: str = "", message: str = "", **values: Any
) -> str:
    values.update(
        status=status,
        error_code=code[:64],
        error_message=message,
        finished_at=timezone.now(),
    )
    ConversionJob.objects.filter(pk=job.pk).update(**values)
    for name, value in values.items():
        setattr(job, name, value)
    return status


def describe(error: BaseException) -> tuple[str, str]:
    """An error's code (the API's, or one of this package's) and its sentence for people."""
    message = str(error)
    if isinstance(error, ConfirmationRequiredError):
        return "confirmationRequired", message
    if isinstance(error, ConversionTimeoutError):
        return "timeout", message
    if isinstance(error, ConversionFailedError):
        return error.code, message
    if isinstance(error, APIError):
        return error.code or f"http{error.status_code}", message
    if isinstance(error, MissingApiKeyError):
        return "missingApiKey", message
    if isinstance(error, APITimeoutError):
        return "connectionTimeout", message
    if isinstance(error, APIConnectionError):
        return "connectionError", message
    return "error", message


def _instance_for(job: ConversionJob, instance: models.Model | None) -> models.Model | None:
    if (
        instance is not None
        and str(instance.pk) == job.object_id
        and job.content_type_id == _content_type(instance, job._state.db).pk
    ):
        return instance
    found: models.Model | None = job.get_object()
    return found


def _run(
    job: ConversionJob,
    instance: models.Model | None,
    client: Any,
    approve: bool,
) -> str:
    if not _claim(job):
        job.refresh_from_db()
        return str(job.status)
    obj = _instance_for(job, instance)
    if obj is None:
        return _finish(job, Status.SKIPPED, "objectDeleted", "The object was deleted first.")
    rule = get_rule(type(obj), job.rule)
    if rule is None:
        return _finish(job, Status.SKIPPED, "ruleRemoved", "The model no longer has this rule.")
    value = getattr(obj, job.field, None)
    if not isinstance(value, FieldFile) or not value.name:
        return _finish(job, Status.SKIPPED, "noFile", "The field has no file any more.")
    if value.name != job.source_name:
        return _finish(job, Status.SKIPPED, "fileChanged", "The file was replaced first.")
    try:
        with _convert(client(), job, rule, value, approve) as result:
            name = _apply(job, rule, obj, value, result)
            credits = result.credits
    except ConverterStudioError as error:
        code, message = describe(error)
        logger.warning(
            "Converter Studio could not convert %s (%s %s): %s %s",
            job.source_name,
            job.content_type.model,
            job.object_id,
            code,
            message,
        )
        return _finish(job, Status.FAILED, code, message)
    except _SourceError as error:
        return _finish(
            job, Status.FAILED, "sourceUnreadable", f"The file could not be read: {error}"
        )
    except _StorageError as error:
        return _finish(
            job, Status.FAILED, "storageError", f"The result could not be saved: {error}"
        )
    except Exception as error:
        logger.exception("Converter Studio: converting %s failed", job.source_name)
        return _finish(job, Status.FAILED, "error", f"{type(error).__name__}: {error}")
    return _finish(job, Status.DONE, credits=credits, result_name=name)


def _idempotency_key(job: ConversionJob, upload_id: str) -> str:
    return f"django-{job.pk}-{upload_id}"


def _create(client: ConverterStudio, job: ConversionJob, rule: Rule, upload_id: str) -> Conversion:
    return client.create_conversion(
        rule.to,
        upload_id=upload_id,
        options=rule.options,
        max_credits=conf.max_credits() if rule.max_credits is None else rule.max_credits,
        idempotency_key=_idempotency_key(job, upload_id),
    )


def _resume(
    client: ConverterStudio, job: ConversionJob, rule: Rule, approve: bool
) -> Conversion | None:
    """The conversion an earlier run started, or ``None`` to start afresh."""
    try:
        current = client.get_conversion(job.conversion_id)
    except NotFoundError:
        # The upload went in but the conversion was never made: make it (the same key).
        try:
            return _create(client, job, rule, job.conversion_id)
        except (NotFoundError, ConflictError):
            return None
    if current.status in _GONE:
        return None
    if current.status == "quoted" and approve:
        return client.confirm(current)
    return current


def _convert(
    client: ConverterStudio, job: ConversionJob, rule: Rule, value: FieldFile, approve: bool
) -> services.ConvertedFile:
    name = services.source_name(value)
    conversion = _resume(client, job, rule, approve) if job.conversion_id else None
    if conversion is None:
        try:
            with services._readable(value) as readable:
                upload = client.upload(readable, file_name=name)
        except OSError as error:
            raise _SourceError(str(error)) from error
        _finish_partial(job, conversion_id=upload.id)
        conversion = _create(client, job, rule, upload.id)
    done = client.wait(conversion, timeout=conf.timeout())
    return services.download(client, done, services.result_name(done, name, rule.to))


def _finish_partial(job: ConversionJob, **values: Any) -> None:
    ConversionJob.objects.filter(pk=job.pk).update(**values)
    for key, value in values.items():
        setattr(job, key, value)


def _dimensions(field: models.Field[Any, Any], instance: models.Model) -> dict[str, Any]:
    if not isinstance(field, models.ImageField):
        return {}
    names = (getattr(field, "width_field", None), getattr(field, "height_field", None))
    return {name: getattr(instance, name) for name in names if name}


def _apply(
    job: ConversionJob,
    rule: Rule,
    instance: models.Model,
    value: FieldFile,
    result: services.ConvertedFile,
) -> str:
    """Saves the result (through storage) where the rule says and updates the row."""
    model = type(instance)
    updates: dict[str, Any] = {}
    original = value.name
    try:
        if rule.target is None:
            value.save(result.name, result.file, save=False)
            name = value.name
            updates[value.field.attname] = name
            updates.update(_dimensions(value.field, instance))
        else:
            target = model._meta.get_field(rule.target)
            if isinstance(target, models.FileField):
                target_file = getattr(instance, rule.target)
                target_file.save(result.name, result.file, save=False)
                name = target_file.name
                updates[target.attname] = name
                updates.update(_dimensions(target, instance))
            else:
                text = result.read_text().strip()
                if isinstance(target, models.CharField) and target.max_length:
                    text = text[: target.max_length]
                setattr(instance, target.attname, text)  # type: ignore[union-attr]
                updates[target.attname] = text  # type: ignore[union-attr]
                name = ""
    except OSError as error:
        raise _StorageError(str(error)) from error
    model._base_manager.using(instance._state.db).filter(pk=instance.pk).update(**updates)
    delete = conf.delete_originals() if rule.delete_original is None else rule.delete_original
    if rule.replaces and delete and original and name != original:
        try:
            value.storage.delete(original)
        except Exception:
            logger.exception("Converter Studio: could not delete the original %s", original)
    answers = file_converted.send_robust(
        sender=model,
        instance=instance,
        job=job,
        rule=rule,
        original_name=original,
        name=name,
    )
    for receiver, answer in answers:
        if isinstance(answer, Exception):
            logger.error(
                "Converter Studio: a file_converted receiver (%s) failed", receiver, exc_info=answer
            )
    return name or posixpath.basename(result.name)
