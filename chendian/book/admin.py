#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import absolute_import, print_function, unicode_literals

from django.contrib import admin
from django.core import urlresolvers
from django.utils.html import format_html

from .models import Book


class BookAdmin(admin.ModelAdmin):
    list_display = ('pk', 'name', 'created_at', 'updated_at')
    list_filter = ('created_at', 'updated_at')
    search_fields = ('name',)
admin.site.register(Book, BookAdmin)
