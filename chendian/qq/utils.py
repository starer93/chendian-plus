#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import absolute_import, print_function, unicode_literals

import logging
import re

from django.conf import settings
from django.utils.timezone import now

from django_rq import job

from core.utils import (
    str_to_utc, default_datetime_start, default_datetime_end
)
from member.models import NewMember
from qq.models import RawMessage, CheckinRecord, UploadRecord
from book.models import Book

logger = logging


class Parser(object):
    def __init__(self, text, msg_handlers=None):
        self.text = text.replace('\r\n', '\n')
        self.r_msg = re.compile(r"""
            (?<=\n)
            (?P<date>\d{4}\-\d{1,2}\-\d{1,2}\s+\d{1,2}:\d{1,2}:\d{1,3})  # date
            \s+
            (?P<nick_name>.*?)                                   # nick_name
            (?:\((?P<qq>\d+)\)|<(?P<email>[^>]+)>)\n             # QQ number
            (?P<msg>.*?)                                         # message
            (?=(?:\d{4}-\d{1,2}-\d{1,2})|\n+$)
        """, re.I | re.X | re.S | re.U)
        self.msg_handlers = []
        if msg_handlers:
            self.msg_handlers.extend(msg_handlers)

    def parse(self):
        for m in self.r_msg.finditer(self.text):
            raw_item = m.group(0)
            date_str = m.group('date')
            nick_name = m.group('nick_name')
            qq = m.group('qq')
            email = m.group('email')
            msg = m.group('msg')
            qq = qq or email
            yield {
                'raw_item': raw_item.strip(),
                'nick_name': re.sub(r'【\d+】', '', nick_name, re.U).strip(),
                'qq': qq.strip(),
                'sn': self._find_sn(nick_name),
                'msg': msg.strip(),
                'posted_at': str_to_utc(date_str),
            }

    def _find_sn(self, nick_name):
        m = re.findall(r'(?<=【)\d+(?=】)', nick_name, re.U)
        if m:
            return int(m[0])

    def __call__(self):
        for msg in self.parse():
            yield msg


def save_to_raw_db(msg_dict, callbacks=None):
    raw_item = msg_dict['raw_item']
    nick_name = msg_dict['nick_name']
    qq = msg_dict['qq']
    sn = msg_dict['sn']
    msg = msg_dict['msg']
    posted_at = msg_dict['posted_at']

    d = RawMessage.objects.filter(
        qq=qq, posted_at=posted_at
    )
    if d.exists():
        raw_msg = d[0]
    else:
        raw_msg = RawMessage()
        raw_msg.raw_item = raw_item
        raw_msg.nick_name = nick_name
        raw_msg.qq = qq
        raw_msg.sn = sn
        raw_msg.msg = msg
        raw_msg.posted_at = posted_at
        raw_msg.save()

    if callbacks:
        for callback in callbacks:
            callback(raw_msg)

    return raw_msg


def save_to_checkin_db(raw_msg, regex=settings.CHECKIN_RE):
    nick_name = raw_msg.nick_name
    qq = raw_msg.qq
    sn = raw_msg.sn
    msg = raw_msg.msg
    m = regex.match(msg)
    if not m:
        return
    if len(qq) > 50:
        qq = qq[:50]
    if len(nick_name) > 50:
        nick_name = nick_name[:50]

    # keyword = m.group('keyword')
    book_name = m.group('book_name').strip('《》')
    if len(book_name) > 60:
        book_name = book_name[:60]
    think = m.group('think').strip()
    posted_at = raw_msg.posted_at

    records = CheckinRecord.objects.filter(
        qq=qq, posted_at=posted_at
    )
    if records.exists():
        record = records[0]
    else:
        record = CheckinRecord()
        record.raw_msg = raw_msg
        record.nick_name = nick_name
        record.qq = qq
        record.sn = sn
        record.book_name = book_name
        record.think = think
        record.posted_at = posted_at
        record.save()
    return record


def save_new_member(checkin_item):
    qq = checkin_item.qq
    sn = checkin_item.sn
    nick_name = checkin_item.nick_name
    if not (sn and qq):
        return

    member = NewMember.objects.filter(qq=qq)
    if not member.exists():
        member = NewMember()
        member.sn = sn
        member.qq = qq
        member.nick_name = nick_name
        member.save()
    else:
        member = member[0]
    return member


def save_new_book(checkin_item):
    book_name = checkin_item.book_name
    if not book_name:
        return

    book = Book.objects.filter(name=book_name)
    if not book.exists():
        book = Book.objects.create(
            name=book_name
        )
    else:
        book = book[0]
    return book


def record_filter_kwargs(request, enable_default_range=True):
    filter_by = request.GET.get('filter_by')
    filter_value = request.GET.get('filter_value', '').strip()
    try:
        datetime_start = str_to_utc(
            request.GET.get('datetime_start', '') + ':00',
            default=default_datetime_start() if enable_default_range else None
        )
    except:
        datetime_start = None
    try:
        datetime_end = str_to_utc(
            request.GET.get('datetime_end', '') + ':00',
            default=default_datetime_end() if enable_default_range else None
        )
    except:
        datetime_end = None
    kwargs = {}
    if filter_value:
        if filter_by == 'sn':
            if filter_value.isdigit():
                kwargs['sn'] = filter_value
        elif filter_by == 'nick_name':
            kwargs['nick_name__contains'] = filter_value
        elif filter_by in ['qq', 'book_name']:
            kwargs[filter_by] = filter_value
    if datetime_start:
        kwargs['posted_at__gte'] = datetime_start
    if datetime_end:
        kwargs['posted_at__lte'] = datetime_end

    return kwargs


@job
def save_uploaded_text(pk, text):
    r = UploadRecord.objects.get(pk=pk)

    try:
        p = Parser(text)
        msg_list = []
        for item in p():
            raw_item = save_to_raw_db(item)
            check_in = save_to_checkin_db(raw_item)
            # TODO 改为使用信号的方式
            if check_in:
                save_new_member(check_in)
                save_new_book(check_in)
            msg_list.append(raw_item)

        r.count = len(msg_list)
        r.status = UploadRecord.status_finish
    except Exception as e:
        logger.exception(e)
        r.status = UploadRecord.status_error
    r.update_at = now()
    r.save()
