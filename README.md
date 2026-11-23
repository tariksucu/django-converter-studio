# Converter Studio for Django and Wagtail

Convert uploaded files in Django and Wagtail with [Converter Studio](https://converter.studio):
iPhone photos (HEIC) and camera RAW photos become JPG, Office documents get a PDF, scans and
pictures give their text to a text field (OCR), videos become MP4. The conversion runs on
Converter Studio's servers, so there is nothing to install on yours: no ImageMagick, no FFmpeg, no
LibreOffice, no Tesseract.

```python
from django.db import models
from django_converter_studio import ConverterStudioMixin, Rule, formats


class Photo(ConverterStudioMixin, models.Model):
    image = models.FileField(upload_to="photos/")

    converter_studio_rules = [
        Rule(field="image", sources=formats.HEIC + formats.RAW, to="jpg"),
    ]
```

Upload `IMG_1234.HEIC` (in the admin, a form or your own code) and the object is saved with
`photos/IMG_1234.jpg`.

- **Rules** on your models: replace a file in place, write the result into another file field, or
  the result's text into a text field.
- Runs **inline** right after the save is committed, or in the background through **Django's
  tasks framework** (Django 6.0+, or the `django-tasks` backport on Django 5.2).
- Works with **any storage**: files are read and written through the field's `Storage` (the file
  system, S3, Google Cloud, Azure...).
- An admin action **"Convert with Converter Studio"**, a **conversions log** in the admin with the
  cost and the API's reason for every failure, a **management command** for files already
  stored, and **system checks** for the settings and the rules.
- **Wagtail**: images Wagtail cannot open (HEIC, camera RAW, EPS and AI artwork) are converted
  while they upload, documents can become PDF, and both listings get a bulk action.
- Built on the official Python client,
  [converter-studio](https://github.com/tariksucu/converter-studio-python).

## Requirements

- Python 3.11 or later.
- Django 5.2 (LTS), 6.0 or 6.1.
- Wagtail 7.4 (LTS), 8.0 or 8.1, for the Wagtail part (optional).
- A Converter Studio account and an API key. Free accounts get credits every day; most photos
  and documents cost 1 credit, reading the text of a picture (OCR) a little more; audio and video
  are priced by their length (video also by its frame size and the format made). See
  [pricing](https://converter.studio/pricing).

## Installation

```console
$ pip install django-converter-studio            # Django
$ pip install "django-converter-studio[wagtail]" # Django and Wagtail
```

```python
# settings.py
INSTALLED_APPS = [
    # ...
    "django_converter_studio",
]
```

```console
$ python manage.py migrate      # the conversions log
```

Create an API key on your [account page](https://converter.studio/account#api-keys) (keys start
with `cvs_live_`; keep them secret) and put it in the environment of your web server and workers:

```console
$ export CONVERTER_STUDIO_API_KEY=cvs_live_...
```

Or set `CONVERTER_STUDIO_API_KEY` in your settings, read from wherever you keep secrets.
`python manage.py converter_studio_account` checks the key and shows the plan and the credits
left; `python manage.py check` tells you when something is not set up right.

## Rules

A rule converts the files of one `FileField` (or `ImageField`) whose extension is in `sources` to
the format `to`. Give a model a `converter_studio_rules` list (the `ConverterStudioMixin` adds
`convert_files()` and declares the attribute), or register rules for a model you do not own from
your `AppConfig.ready()`:

```python
from django_converter_studio import Rule, formats, register

register(Document, Rule(field="file", sources=formats.OFFICE, to="pdf", target="pdf"))
```

Where the result goes:

```python
class Report(ConverterStudioMixin, models.Model):
    file = models.FileField(upload_to="reports/")
    pdf = models.FileField(upload_to="reports/pdf/", blank=True)
    text = models.TextField(blank=True)

    converter_studio_rules = [
        # Office documents get a PDF next to them, in another file field.
        Rule(field="file", sources=formats.OFFICE, to="pdf", target="pdf"),
        # Pictures and scanned PDFs give their text to a text field (OCR).
        Rule(
            field="file",
            sources=(*formats.OCR_IMAGES, "pdf"),
            to="txt",
            target="text",
            options={"ocr": True},
        ),
    ]


class Clip(ConverterStudioMixin, models.Model):
    video = models.FileField(upload_to="clips/")

    converter_studio_rules = [
        # Replaced in place (no target): talk.mov becomes talk.mp4, at most 720p.
        Rule(field="video", sources=formats.VIDEO, to="mp4", options={"height": "720"}, run="task"),
    ]
```

| `Rule(...)`       | What it does                                                                               |
| ----------------- | ------------------------------------------------------------------------------------------ |
| `field`           | the file field whose files are converted                                                   |
| `sources`         | the extensions converted (`formats.HEIC`, `RAW`, `OFFICE`, `VIDEO`, `AUDIO`, `OCR_IMAGES`) |
| `to`              | the format made: `jpg`, `png`, `webp`, `pdf`, `txt`, `docx`, `mp4`, `mp3`...               |
| `target`          | none: replace the file in place; a file field: save the result there; a text field: text   |
| `options`         | the API's conversion settings, such as `{"quality": "high"}` or `{"height": "720"}`        |
| `max_credits`     | the most one file may cost to start on its own (`CONVERTER_STUDIO_MAX_CREDITS`, 20)        |
| `run`             | `"inline"` or `"task"` (`CONVERTER_STUDIO_RUN`)                                            |
| `delete_original` | delete a replaced original from storage (`CONVERTER_STUDIO_DELETE_ORIGINALS`, off)         |
| `name`            | how the rule is shown in the conversions log (made up when not given)                      |

The settings each conversion takes are listed on the [API page](https://converter.studio/developers).
A replaced file keeps the directory its field's `upload_to` gives it, and the storage picks a free
name (`IMG_1234.jpg`, then `IMG_1234_a8Kd0Ze.jpg`). Django never deletes replaced files on its
own, and neither does this package unless you ask it to. `ImageField` width and height fields
follow the new file.

### When files are converted

A file is converted when it is **new**: an upload, or a `File` assigned in code, saved with the
object. Saving an object without changing its file does nothing, and so does loading fixtures. A
conversion runs **after the save is committed**, never inside your transaction:

- `run="inline"`: in the same process, before the request that saved the object ends (the admin
  shows the converted file right away). Fine for photos and documents, which take a second or two.
- `run="task"`: queued with Django's tasks framework and run by your worker. Use it for videos.
  Django 6.0 and later have the framework built in; on Django 5.2 install the backport,
  [`django-tasks`](https://pypi.org/project/django-tasks/) (Wagtail installs it already). Django
  itself ships only an immediate backend, which runs the task at once; for real background work
  configure a backend with a worker, for example
  [`django-tasks-db`](https://pypi.org/project/django-tasks-db/):

  ```python
  INSTALLED_APPS += ["django_tasks_db"]
  TASKS = {"default": {"BACKEND": "django_tasks_db.DatabaseBackend", "QUEUES": ["default"]}}
  ```

  ```console
  $ python manage.py db_worker
  ```

- `CONVERTER_STUDIO_RUN = "auto"` (the default): tasks when a tasks framework is there,
  otherwise inline. Without a framework, `"task"` runs inline too (`manage.py check` says so).

A conversion that fails never breaks the save: the original stays, and the conversions log says
why. The instance you saved follows an inline conversion; one done by a task is in the database,
so call `refresh_from_db()` to see it.

### The admin

- **Admin › Converter Studio › Conversions** lists every conversion: the file, the object, its
  status, what it cost, and for a failure the API's own reason ("This API key does not work.",
  "You have used today's credits."...). "Convert again" runs failed ones again; "Approve the price
  and convert" goes ahead with those that cost more than `max_credits` (nothing is charged before
  that).
- **"Convert with Converter Studio"** converts the selected objects' files by their rules, for
  files stored before the rules existed. Add it with the mixin, or name it in `actions`:

  ```python
  from django_converter_studio.admin import ConverterStudioAdminMixin, convert_with_converter_studio


  @admin.register(Photo)
  class PhotoAdmin(ConverterStudioAdminMixin, admin.ModelAdmin): ...


  @admin.register(Report)
  class ReportAdmin(admin.ModelAdmin):
      actions = [convert_with_converter_studio]
  ```

  On Django 6.1 the action is offered on each object's own page too.

### Management commands

```console
$ python manage.py converter_studio_convert --dry-run          # what would be converted
$ python manage.py converter_studio_convert                     # every model with rules
$ python manage.py converter_studio_convert library.Photo --limit 100
$ python manage.py converter_studio_convert library.Report --field file --force --queue
$ python manage.py converter_studio_account                     # the key, the plan, the credits
```

Files converted already are skipped: a replaced file no longer has a source extension, and a
filled target is left alone unless `--force`. `--queue` hands the conversions to the tasks
framework instead of converting them one after the other. The command ends with an error when a
conversion failed.

### In your own code

```python
from django_converter_studio import convert, convert_to_storage, extract_text, open_client

with convert(photo.image, "webp", options={"quality": "balanced"}) as result:
    photo.preview.save(result.name, result.file)  # result.file is a Django File

name = convert_to_storage(report.file, "pdf")  # saved next to it, through its storage
text = extract_text(scan.file)  # OCR for pictures and scanned PDFs

with open_client() as client:  # the converter-studio client, configured
    print(client.account().credits)
```

`convert()` takes a `FieldFile` (read through its storage), an upload, any Django `File`, a path,
or bytes with `file_name=`. Errors are the client's exceptions (`ConversionFailedError`,
`AuthenticationError`, `InsufficientCreditsError`, `ConfirmationRequiredError`...), whose message
is the API's own sentence, meant for people. `obj.convert_files()` converts one object by its rules.

`django_converter_studio.signals.file_converted` is sent after a converted file is saved (`sender`
is the model, with `instance`, `rule`, `job`, `original_name` and `name`), for example to clear a
cache.

## Wagtail

```python
# settings.py
from django_converter_studio import formats

INSTALLED_APPS = [
    # ...
    "django_converter_studio",
    "django_converter_studio.wagtail",
]

WAGTAILIMAGES_IMAGE_FORM_BASE = "django_converter_studio.wagtail.forms.ConvertingImageForm"
WAGTAILIMAGES_EXTENSIONS = [
    "avif",
    "gif",
    "jpg",
    "jpeg",
    "png",
    "webp",
    *formats.HEIC,
    *formats.RAW,
    *formats.VECTOR,
]
WAGTAILIMAGES_MAX_UPLOAD_SIZE = 50 * 1024 * 1024  # RAW photos are large

# Optional: Office documents become PDF after they upload.
CONVERTER_STUDIO_WAGTAIL_DOCUMENTS = {"docx": "pdf", "doc": "pdf", "odt": "pdf", "pptx": "pdf"}
```

- **Images** are converted while they upload, before Wagtail checks them, in every upload path of
  the admin ("Add an image", "Add images", the image chooser, replacing a file): HEIC and HEIF
  photos and camera RAW photos (CR2, NEF, ARW, DNG) become JPG, EPS and AI artwork becomes PNG.
  Wagtail stores the converted image, with its real size, and makes its renditions from it.
  `CONVERTER_STUDIO_WAGTAIL_IMAGES` changes the list (`{"heic": "webp", ...}`).
- If an image cannot be converted (no credits, a damaged file...), the upload is refused with
  Converter Studio's reason, unless Wagtail can use the original as it is (a HEIC, when Wagtail
  reads HEIC): then the original is kept, and the conversions log says why it was not converted.
- **Documents** in `CONVERTER_STUDIO_WAGTAIL_DOCUMENTS` are converted after they are saved, in
  place: the document keeps its title, collection, tags and links, and Wagtail's file size and
  hash follow the new file.
- The image and document listings get a **"Convert with Converter Studio"** bulk action, for files
  uploaded before.
- The conversions log is in Django's admin (at `/django-admin/` in a project made with
  `wagtail start`).
- `CONVERTER_STUDIO_WAGTAIL_OPTIONS` gives conversion settings per format made, for example
  `{"jpg": {"quality": "high", "keepMetadata": True}}`.
- `WAGTAILIMAGES_EXTENSIONS` must list the extensions to convert, or Wagtail's uploader refuses
  them before the form sees them; `manage.py check` warns about a missing one.
- The "Add an image" file dialog offers the extensions to convert. The "Add images" page's dialog
  filters on images, which on some systems hides EPS and AI files: drag them onto the page, or
  choose "All files" in the dialog.
- With your own image base form, add the mixin:
  `class MyImageForm(ConvertingImageFormMixin, BaseImageForm)`.

Photoshop files (PSD) are not converted: Converter Studio does not read them.

## Settings

| Setting                                      | Default                        | What it does                                                |
| -------------------------------------------- | ------------------------------ | ----------------------------------------------------------- |
| `CONVERTER_STUDIO_API_KEY`                   | the environment variable       | your API key                                                |
| `CONVERTER_STUDIO_BASE_URL`                  | `https://converter.studio/api` | the API's address                                           |
| `CONVERTER_STUDIO_MAX_CREDITS`               | `20`                           | the most one file may cost to start without your approval   |
| `CONVERTER_STUDIO_TIMEOUT`                   | `600`                          | seconds a conversion may take (rules, commands, actions)    |
| `CONVERTER_STUDIO_UPLOAD_TIMEOUT`            | `60`                           | seconds a Wagtail image upload waits for its conversion     |
| `CONVERTER_STUDIO_RUN`                       | `"auto"`                       | `"auto"`, `"inline"` or `"task"`                            |
| `CONVERTER_STUDIO_TASK_BACKEND`, `..._QUEUE` | `"default"`                    | the `TASKS` backend and queue conversions are enqueued on   |
| `CONVERTER_STUDIO_DELETE_ORIGINALS`          | `False`                        | delete a replaced original from storage                     |
| `CONVERTER_STUDIO_WAGTAIL_IMAGES`            | HEIC, RAW → JPG; EPS, AI → PNG | what each image extension becomes while it uploads          |
| `CONVERTER_STUDIO_WAGTAIL_DOCUMENTS`         | `{}`                           | what each document extension becomes after it is saved      |
| `CONVERTER_STUDIO_WAGTAIL_OPTIONS`           | `{}`                           | conversion settings by the format made, for Wagtail's files |

## Limits

- The largest file depends on your plan; files over 95 MB are uploaded in parts on their own.
  Audio and video length depends on the plan too.
- One file in, one file out: no merging or splitting of PDFs.
- An inline conversion keeps its request waiting; use tasks for videos and large files.
- A conversion that costs more than `max_credits` waits for your approval in the conversions log.

## Privacy

The files your rules match are sent to Converter Studio (converter.studio) to be converted, with
their names; nothing else about your site or its users is sent. Uploaded files are deleted as
soon as they are converted, and results 6 hours later. Each request also says which integration
sent it (`X-Converter-Studio-Client: django/<version>`), for usage statistics only. Mention
Converter Studio in your site's privacy policy if your users' files are converted. See the
[privacy policy](https://converter.studio/privacy) and the [terms](https://converter.studio/terms).

The API key is sent only to the API's address, never logged and never shown in the admin.

## Links

- Converter Studio: <https://converter.studio>
- API documentation: <https://converter.studio/developers>
- Pricing: <https://converter.studio/pricing>
- Source code and issues: <https://github.com/tariksucu/django-converter-studio>
- Changelog: <https://github.com/tariksucu/django-converter-studio/blob/main/CHANGELOG.md>
- The Python client: <https://github.com/tariksucu/converter-studio-python>
- Support: <support@converter.studio>

MIT licensed. © Converter Studio.
