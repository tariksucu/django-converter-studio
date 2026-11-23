"""Converter Studio for Wagtail: images Wagtail cannot open become images it can, as they upload.

Add ``"django_converter_studio"`` and ``"django_converter_studio.wagtail"`` to ``INSTALLED_APPS``,
then in the settings::

    from django_converter_studio import formats

    WAGTAILIMAGES_IMAGE_FORM_BASE = "django_converter_studio.wagtail.forms.ConvertingImageForm"
    WAGTAILIMAGES_EXTENSIONS = ["avif", "gif", "jpg", "jpeg", "png", "webp",
                                *formats.HEIC, *formats.RAW, *formats.VECTOR]

==========================================  ==============================================  ========
Setting                                     What it does                                    Default
==========================================  ==============================================  ========
``CONVERTER_STUDIO_WAGTAIL_IMAGES``         extension -> format for images                  below
``CONVERTER_STUDIO_WAGTAIL_DOCUMENTS``      extension -> format for documents               ``{}``
``CONVERTER_STUDIO_WAGTAIL_OPTIONS``        format -> the API's conversion settings         ``{}``
==========================================  ==============================================  ========

Images: HEIC, HEIF and camera RAW (CR2, NEF, ARW, DNG) become JPG, EPS and AI become PNG, while
they upload (before Wagtail checks them). Documents: nothing by default; for example
``{"docx": "pdf", "doc": "pdf", "odt": "pdf", "pptx": "pdf"}`` turns Office documents into PDF
after they are saved (inline, or as a task), in place. Both listings get a "Convert with Converter
Studio" bulk action for files already uploaded.
"""
