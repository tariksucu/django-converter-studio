# Changelog

All notable changes to this package are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the package uses
[semantic versioning](https://semver.org/).

## 1.0.0 - 2026-11-23

The first release, for Django 5.2, 6.0 and 6.1 and Wagtail 7.4, 8.0 and 8.1.

- Rules on models (`converter_studio_rules`, `register()`): replace an uploaded file in place,
  save the result into another file field, or its text into a text field; run inline after the
  save is committed or through Django's tasks framework (Django 6.0+ or the `django-tasks`
  backport); files read and written through any storage.
- The conversions log in the admin, with "Convert again" and "Approve the price and convert"; the
  "Convert with Converter Studio" admin action (also on the object's page on Django 6.1).
- The `converter_studio_convert` management command for files already stored, the
  `converter_studio_account` command, and system checks for the settings and the rules.
- `convert()`, `convert_to_storage()`, `extract_text()` and `open_client()` for your own code, and
  the `file_converted` signal.
- Wagtail: images in formats Wagtail cannot open (HEIC, camera RAW, EPS, AI) converted while they
  upload, documents converted after they are saved, bulk actions on both listings.
