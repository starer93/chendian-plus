#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""统计分析"""

from __future__ import absolute_import, print_function, unicode_literals

import logging

from django.views.generic import ListView

from core.aggregates import CountWithFunc
from qq.models import CheckinRecord
from qq.utils import record_filter_kwargs

logger = logging.getLogger(__name__)


class GroupByQQListView(ListView):
    context_object_name = 'records'
    template_name = 'qq/analysis/group_by_qq.html'
    paginate_by = 50

    def get_queryset(self):
        sort = self.request.GET.get('sort', '-count')
        kwargs = record_filter_kwargs(self.request)
        self.extra_context = {
            'datetime_start': kwargs['posted_at__gte'],
            'datetime_end': kwargs['posted_at__lte'],
            'book_name': kwargs.get('book_name', ''),
        }
        kwargs.update({'deleted': False})

        queryset = CheckinRecord.objects.filter(**kwargs)
        queryset = queryset.values(
            'sn', 'qq', 'nick_name'
        ).annotate(
            # count=CountWithFunc('id', express="date_trunc('day', posted_at)",
            count=CountWithFunc("date(posted_at)", distinct=True)
        )
        logger.debug(queryset.query)
        if sort and sort.lstrip('-') in ['sn', 'nick_name', 'qq', 'count']:
            queryset = queryset.order_by(sort)
        return queryset

    def get_context_data(self, **kwargs):
        context = super(GroupByQQListView, self).get_context_data(**kwargs)
        context.update(self.extra_context)
        return context
